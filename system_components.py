import numpy as np
import pandas as pd
import pvlib
from pvlib.location import Location
from config import PATHS, SITE, PV_panel, ARRAY, PV_system, BESS as BESS_CFG, GENERATOR as GEN_CFG, ECONOMICS

# each physical system asset is an object with physical properties, behaviour, technical constraints and economic parameters 
# first define pv and bess as 2 classes pulling from config parameters, also define load as a class to easily handle dispatch alter 
#these can then take anyyyy type of component we assign them to during the optimisation (since we have defined their __init__ to create an object for each separate capacity)

################################ PV ######################################
class PVmodel:
    def __init__(self, PATHS, SITE, ARRAY, PV_panel, PV_system, pv_capacity_kwp):
        self.paths = PATHS
        self.site = SITE
        self.array = ARRAY
        self.panel = PV_panel
        self.pvsystem = PV_system
        self.pv_capacity_kwp = pv_capacity_kwp

        self.tmy = self._load_tmy()
        self.per_unit_profile = self._generate_per_unit_profile()

    def _load_tmy(self): 
        raw = pd.read_csv(self.paths["tmy"], comment="#", skiprows=0)
        
        # 1. Parse UTC time and convert to your site's local timezone
        raw['time(UTC)'] = pd.to_datetime(raw['time(UTC)'], format="%Y%m%d:%H%M", utc=True)
        raw = raw.set_index("time(UTC)").tz_convert(self.site["timezone"])
        
        # 2. Extract the local month, day, and hour
        local_months = raw.index.month
        local_days = raw.index.day
        local_hours = raw.index.hour
        
        # 3. Create a clean, unified Series of datetimes
        clean_dates = pd.to_datetime({
            'year': 2023,
            'month': local_months,
            'day': local_days,
            'hour': local_hours
        })
        
        # 4. Convert to DatetimeIndex and Localize
        raw.index = pd.DatetimeIndex(clean_dates).tz_localize(self.site["timezone"])
        
        # 5. Sort chronologically. This perfectly aligns Jan 1, 00:00 to row 0.
        raw = raw.sort_index()
        
        # 6. Slice exactly 8760 hours
        raw = raw.iloc[:8760]
        
        # 7. Return the cleaned dataframe. 
        return pd.DataFrame({
            "ghi": pd.to_numeric(raw["G(h)"], errors="coerce").clip(lower=0),
            "dni": pd.to_numeric(raw["Gb(n)"], errors="coerce").clip(lower=0),
            "dhi": pd.to_numeric(raw["Gd(h)"], errors="coerce").clip(lower=0),
            "temp_air": pd.to_numeric(raw["T2m"], errors="coerce"),
        }).fillna(0)
    
    def _generate_per_unit_profile(self):
        loc = Location(self.site["lat"], self.site["long"], self.site["timezone"], self.site["alt"])
        solar_pos = loc.get_solarposition(self.tmy.index)
        poa = pvlib.irradiance.get_total_irradiance(
            surface_tilt    = self.array["tilt_deg"],
            surface_azimuth = self.array["azimuth_deg"],
            solar_zenith    = solar_pos["apparent_zenith"],
            solar_azimuth   = solar_pos["azimuth"],
            dni             = self.tmy["dni"],
            ghi             = self.tmy["ghi"],
            dhi             = self.tmy["dhi"],
            dni_extra       = pvlib.irradiance.get_extra_radiation(self.tmy.index),
            model           = "perez",
            albedo          = self.array["albedo"],
            )
        G_POA = poa["poa_global"].clip(lower=0)   #W/m2 on tilted panel surface
        T_cell = self.tmy["temp_air"] + G_POA * (self.panel["T_noct"] - 20) / 800  # nominal operating cell temperature (NOCT) model
        P_DC_per_kWp = ((G_POA / 1000) * (1 + (self.panel["gamma_eff"] / 100) * (T_cell - 25))).clip(lower=0)   # no negative output
        P_AC_per_kWp = P_DC_per_kWp * self.pvsystem["inverter_eff"]   # kW per kWp
        return P_AC_per_kWp
    
    def get_generation(self, capacity_kWp):
        return self.per_unit_profile * capacity_kWp

############################### BESS #####################################
class BESSmodel: 
    def __init__(self, E_max_kwh, P_max_kw, BESS_CFG, ECONOMICS):
        self.E_max_kwh = E_max_kwh
        self.P_max_kw = P_max_kw
        self.ch_eff = BESS_CFG["ch_eff"]
        self.dis_eff = BESS_CFG["dis_eff"]
        self.self_discharge = BESS_CFG["self_discharge"]
        self.min_soc = BESS_CFG["min_soc"]
        self.max_soc = BESS_CFG["max_soc"]
        self.init_soc = BESS_CFG["init_soc"]
        self.soc_reserve = BESS_CFG["soc_reserve"]
        self.c_rate_max = BESS_CFG["c_rate_max"]
        self.lifetime_yr = BESS_CFG["lifetime_yr"]
        self.capex_kwh = BESS_CFG["capex_kwh"]
        self.capex_kw = BESS_CFG["capex_kw"]
        self.opex_kwh_yr = BESS_CFG["opex_kwh_yr"]
        self.replacement_cost_kwh = BESS_CFG["replacement_cost_kwh"]
        self.discount_rate = ECONOMICS["discount_rate"]
        self.proj_lifetime = ECONOMICS["project_lifetime"]


    ### soc limits in absolut kwh
    @property
    def soc_min_kwh(self): 
        return self.min_soc * self.E_max_kwh
    
    @property
    def soc_max_kwh(self):
        return self.max_soc * self.E_max_kwh
    
    @property
    def init_soc_kwh(self): 
        return self.init_soc * self.E_max_kwh
    
    @property
    def soc_reserve_kwh(self): 
        return self.soc_reserve * self.E_max_kwh
    
    @property
    def usable_kwh(self): 
        return self.soc_max_kwh - self.soc_min_kwh

    ### power limits
    @property 
    def p_max_chg(self): 
        return min(self.P_max_kw, self.c_rate_max * self.E_max_kwh) 

    @property
    def p_max_dis(self): 
        return min(self.P_max_kw, self.c_rate_max * self.E_max_kwh)

    ### cost calculations
    @property 
    def capex_total_jpy(self): 
        return self.capex_kwh * self.E_max_kwh + self.capex_kw * self.P_max_kw

    @property
    def annual_opex_jpy(self): 
        return self.opex_kwh_yr * self.E_max_kwh

############################### LOAD #####################################
class Loadmodel: 
    def __init__(self, PATHS):
        self.demand = pd.read_csv(PATHS["pilot_load"], sep=',', decimal='.')
        self.demand_profile = pd.to_numeric(self.demand['GRID_kWh'], errors='coerce').fillna(0).values[:8760]
    def get_demand(self):
        return self.demand_profile
    
    def get_evacuation_demand(self):

        #24 hour profiles for winter and summer - are there per room????
        winter_24h = [
            0.825, 0.825, 0.825, 0.825, 0.825, 0.825, 
            0.366666667, 0.366666667, 0.366666667, 0.366666667, 0.366666667, 0.366666667, 
            0.366666667, 0.366666667, 0.366666667, 0.366666667, 0.366666667, 0.366666667, 
            1.991666667, 1.991666667, 1.991666667, 1.991666667, 1.991666667, 1.991666667
        ]
        
        summer_24h = [
            0.825, 0.825, 0.825, 0.825, 0.825, 0.825, 
            0.266666667, 0.266666667, 0.266666667, 0.266666667, 0.266666667, 0.266666667, 
            0.266666667, 0.266666667, 0.266666667, 0.266666667, 0.266666667, 0.266666667, 
            1.675, 1.675, 1.675, 1.675, 1.675, 1.675
        ]
        
        days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        heating_months = [1, 2, 3, 11, 12]  
        evac_8760 = []
        
        for month_idx, days in enumerate(days_in_month):
            current_month = month_idx + 1
            
            # Select profile based on heating season
            daily_profile = winter_24h if current_month in heating_months else summer_24h
                
            # Tile the chosen profile for every day in this month
            for _ in range(days):
                evac_8760.extend(daily_profile)
                
        num_rooms = 4
        evac_8760_scaled = np.array(evac_8760) * num_rooms
                
        return np.array(evac_8760)