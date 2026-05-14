### file paths 
PATHS = {
    "pilot_load": r"C:/Users/myrsi/Desktop/MSc Thesis/Supply Modeling/Total_demand_hourly.csv",
    "tmy": r"C:/Users/myrsi/Desktop/MSc Thesis/Supply Modeling/odaka_tmy.csv",
    "outputs": r"C:/Users/myrsi/Desktop/MSc Thesis/Supply Modeling/outputs"
}
### site information
SITE = {
    "lat": 37.56,
    "long": 140.99,
    "alt": 25, ##google? 25m 
    "timezone": "Asia/Tokyo"
}

### PV panel data (Hansol Technics Co. Ltd. HS 400 XA-CLEA0 - Mono-c-Si)
PV_panel = {
    "p_rated_wp" : 400,             #rated power 400
    "area_m2" : 1.9,                #module area in m2
    "nom_eff" : 0.21,               #30.30%
    "T_noct" : 45,                  #oC
    "gamma_eff": -0.35,
    "cells_in_series": 54           # number of cells 
}

ARRAY = {
    "tilt_deg": 37,
    "azimuth_deg": 180, 
    "albedo": 0.20 
}

PV_system = {
    "inverter_eff": 0.97,           #placeholder now - find actual model
    "dc_ac_ratio": 1.2, 
    "system_losses": 0.14,          #total DC+AC system losses (wiring, soiling,etc)
    "CAPEX_pv_jpy_kwp": 123750,     #JPY/kWp installed according to the National Survey Report of PV Power Applications in JAPAN - aggregated data from 2021 report
    "OPEX_pv_jpy_kwp": 3100         #JPY/kWp/year
    }

### BESS - LFP 
BESS = {
    "ch_eff": 0.95, 
    "dis_eff": 0.95, 
    "self_discharge": 0.0002,       #fraction of stored energy lost per hour
    "min_soc": 0.10,                #to protect battery - probably will change to 20%
    "max_soc": 0.90,                #to avoid overcharge
    "init_soc": 0.50,               #initial state of charge - choose assumption/ can test different ones
    "soc_reserve": 0.20,            #emergency reserve - active during disaster
    "c_rate_max": 1.0,              #max charge/discharge rate 
    ###battery degradation
    "cycle_life": 4000,             #number of cycles based on LFP chemistry
    "dod_ref":  0.80,               #depth of discharge reference 
    "eol": 0.80,                    #end of life
    "calendar_fade_per_year": 0.005, #0.5% standard reference point from lit
    "salvage_fraction": 0.10, 
    ###thermal 
    "t_min_op_c"     : -10,         #minimum operating temperature (oC)
    "t_max_op_c"     :  45,
    "t_charge_inhibit": 0,          #charging inhibited below this temperature (°C)
    ###costs
    #"bess_subsidy_rate": 0.30, 
    "capex_kwh"      : 106000,      #JPY/kWh turnkey cost (92k +14k installation costs /kwh) (METI)
    #"capex_kw"       : 20000,       #JPY/kW  (power capacity component)
    "opex_kwh_yr"    : 1500,        #JPY/kWh/yr
    "lifetime_yr"    : 15,          #calendar life (years)
    "replacement_cost_kwh": 60000,  #JPY/kWh at end of life
}


### Backup Generator
GENERATOR = {
    "gen_type"       : "diesel",      #"diesel" or "biogas"
    "p_min_frac"     : 0.25,          #minimum stable generation as fraction of rated
    ###piecewise linear fuel curve: F(P) = a * C_gen + b * P_gen  (litres/h)
    "fuel_a"         : 0.08,          #no-load coefficient  (L/kWh)
    "fuel_b"         : 0.25,          #marginal fuel rate   (L/kWh)
    "fuel_cost_jpy"  : 160,           #JPY per litre (diesel) or m3 (biogas)
    "co2_kg_per_l"   : 2.68,          #kgCO2 per litre (diesel)
    ###unit commitment (MILP)
    "t_min_up_h"     : 2,             #minimum up time (hours)
    "t_min_down_h"   : 1,             #minimum down time (hours)
    "startup_cost"   : 500,           #JPY per cold start
    "fixed_cost_h"   : 200,           #JPY per committed hour (maintenance amortised)
    # costs
    "capex_kw"       : 120000,        #JPY/kW
    "opex_kwh"       : 5,             #JPY/kWh generated
    "lifetime_yr"    : 20,
}
### Demand
LOAD = {
    "annual_kwh"     : 850000,       #district total annual energy (kWh/yr)
    "peak_kw"        : 250,           #estimated peak demand (kW)
    "critical_frac"  : 0.30,          #fraction of load classified as critical
}

### Economics 
ECONOMICS = {
    "project_lifetime": 25,           #years
    "discount_rate"  : 0.04,          # discount rate (4%)
    "inflation_rate" : 0.015,          #JPY inflation
    "currency"       : "JPY",
}
### Resilience 
RESILIENCE = {
    "pv_damage_factor"    : 0.3,      #fraction of PV remaining after damage event
    "demand_surge_factor" : 1.5,      #load multiplier during disaster
    "fuel_cutoff_hours"   : 72,       #hours generator is unavailable
    "bess_fade_factor"    : 0.7,      #fraction of BESS capacity remaining
    "low_irr_days"        : 5,        #consecutive low-irradiance days (GHI × 0.15)
}

### MOPSO
MOPSO = {
    "n_particles"    : 100,            #population size
    "n_iterations"   : 150,           #max iterations
    "w_start"        : 0.9,           #inertia weight at iteration 0
    "w_end"          : 0.4,           #inertia weight at final iteration
    "c1"             : 1.5,           #cognitive coefficient
    "c2"             : 1.5,           #social coefficient
    "archive_size"   : 500,           #max Pareto archive size
    "n_grid_divs"    : 30,            #hypergrid divisions per objective axis
    "penalty_lambda" : 1e6,           #constraint violation penalty weight
    "n_jobs"         : -1,            #parallel workers (-1 = all cores)
    # search bounds for each sizing variable  [min, max]
    "bounds": {
        "C_PV_kwp"   : [0,   5000],   #total PV capacity (kWp) based on high potential area calculated from soalr clustering
        "E_BESS_kwh" : [100,   5000],   #BESS energy capacity (kWh)
        "P_BESS_kw"  : [0,   5000],    #BESS power rating (kW)
    },
    "objectives"     : ["TAC", "ss"],   #can add "CO2" as third objective
}

### Dispatch
DISPATCH = {
    "mode"           : "MILP",          #"LP" or "MILP"
    "timestep_h"     : 1,             #hourly resolution
    "n_timesteps"    : 8760,          #hours per year
    "solver"         : "gurobi",      #LP/MILP solver - appsi_highs
    "grid_price"     : 36.37,           #JPY/kWh grid price tepco
    "re_levy"        : 4.18,            #jpy/kwh re levy
    "wheeling_charge": 10.31,
    "max_export_limit_kw": 650,
    "feed_in_tariff": 10.81,             #jpy/kwh sold to the grid
    "curtail_penalty": 1,             #JPY/kWh 
    # rolling horizon (set to 8760 for full-year solve, smaller for MILP speedup)
    "horizon_h"      : 8760,
}
 