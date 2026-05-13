import numpy as np 
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverFactory, SolverStatus, TerminationCondition
import matplotlib.pyplot as plt
import os
import pvlib 
from pvlib.location import Location
from config import PATHS, ECONOMICS, DISPATCH
from system_components import PVmodel, BESSmodel 

#dispatch as a class for easy handling
class DispatchOptimizer:
    def __init__(self, pv_system, bess_system, load_system, dispatch_cfg, grid_status=None):
        """
        pv_system   : Instance of PVmodel
        bess_system : Instance of BESSmodel
        load_system : Instance of Loadmodel
        dispatch_cfg: The DISPATCH dictionary from config.py
        """
        self.pv = pv_system
        self.bess = bess_system
        self.load = load_system
        self.cfg = dispatch_cfg

       
        if grid_status is None:
            self.grid_status = np.ones(8760) # Default: Grid is 100% healthy
        else:
            self.grid_status = grid_status   # Use the stress test array
           
        #determine simulation length - annual hourly so 8760
        self.T = len(self.load.get_demand())
        
    def solve(self):
        pv_gen_raw = self.pv.get_generation(self.pv.pv_capacity_kwp).to_numpy()[:self.T].astype(float)  #has some nans - look into tmy file but for now just fill to run code
        pv_gen_data = np.nan_to_num(pv_gen_raw, nan=0.0)
        load_data = self.load.get_demand()[:self.T].astype(float)
       
        ###########  create model  ###########
        model = pyo.ConcreteModel(name="InnerLoop_Dispatch")
        model.t = pyo.RangeSet(0, self.T - 1)

        ###########  define decision variables (POWER STREAMS) ###########
        #Where does the PV go?
        model.p_pv2load = pyo.Var(model.t, domain=pyo.NonNegativeReals)
        model.p_pv2bess = pyo.Var(model.t, domain=pyo.NonNegativeReals)
        model.p_pv2grid = pyo.Var(model.t, domain=pyo.NonNegativeReals)
        model.p_curtailment = pyo.Var(model.t, domain=pyo.NonNegativeReals)


        #How is the load met?
        model.p_bess2load = pyo.Var(model.t, domain=pyo.NonNegativeReals)
        model.p_grid2load = pyo.Var(model.t, domain=pyo.NonNegativeReals)
        model.p_unmet = pyo.Var(model.t, domain=pyo.NonNegativeReals)

        # Battery states
        model.b_is_charging = pyo.Var(model.t, domain=pyo.Binary)
        model.soc = pyo.Var(pyo.RangeSet(0, self.T), domain=pyo.NonNegativeReals, bounds=(self.bess.soc_min_kwh, self.bess.soc_max_kwh))

        ###########  define objective function  ###########         
        def objective_rule(m):
            import_cost = sum(m.p_grid2load[t] * (self.cfg["grid_price"]) for t in m.t)
            wheeling_cost = sum((m.p_pv2load[t] + m.p_bess2load[t]) * (self.cfg["wheeling_charge"] + self.cfg["re_levy"]) for t in m.t)
            export_revenue = sum((m.p_pv2grid[t] * (1 - 0.0496)) * self.cfg["feed_in_tariff"] for t in m.t) #revenue - only get paid for 95.04% of the PV we send to the grid due to 4.96% congestion curtailment
            avoided_import_cost = sum(m.p_bess2load[t] * self.cfg["grid_price"] for t in m.t)
            curtailment_penalty = sum(m.p_curtailment[t] * 0.1 for t in m.t)
            return import_cost + wheeling_cost + curtailment_penalty - export_revenue   #- avoided_import_cost
        model.obj = pyo.Objective(rule=objective_rule, sense=pyo.minimize)  

        ###########  define model constraints  ###########
        model.init_soc_cons = pyo.Constraint(expr= model.soc[0] == self.bess.init_soc_kwh)
        
        
        #demand has to be met at all times
        def demand_must_be_met_rule(m, t):
            # During healthy grid hours, force unmet demand to be zero
            if self.grid_status[t] > 0.5:
                return m.p_unmet[t] == 0
            return pyo.Constraint.Skip
        model.no_unmet_demand = pyo.Constraint(model.t, rule=demand_must_be_met_rule)

        #PV Generation Limit
        def pv_limit_rule(m, t):
            return m.p_pv2load[t] + m.p_pv2bess[t] + m.p_pv2grid[t] + m.p_curtailment[t] == pv_gen_data[t]
        model.pv_limit = pyo.Constraint(model.t, rule=pv_limit_rule)
        
        #Load Balance: The sum of streams going to the load MUST exactly equal the demand
        def load_balance_rule(m, t):
            return m.p_pv2load[t] + m.p_bess2load[t] + m.p_grid2load[t] + m.p_unmet[t] == load_data[t]
        model.load_balance = pyo.Constraint(model.t, rule=load_balance_rule)
        

        def charge_limit_rule(m, t):
            return m.p_pv2bess[t] <= self.bess.p_max_chg
        model.charge_limit = pyo.Constraint(model.t, rule=charge_limit_rule)

        def discharge_limit_rule(m, t):
            return m.p_bess2load[t] <= self.bess.p_max_dis
        model.discharge_limit = pyo.Constraint(model.t, rule=discharge_limit_rule)

        def charge_binary_rule(m, t):
            return m.p_pv2bess[t] <= m.b_is_charging[t] * self.bess.p_max_chg
        model.charge_logic = pyo.Constraint(model.t, rule=charge_binary_rule)

        def discharge_binary_rule(m, t):
            return m.p_bess2load[t] <= (1 - m.b_is_charging[t]) * self.bess.p_max_dis
        model.discharge_logic = pyo.Constraint(model.t, rule=discharge_binary_rule)

        #SOC Temporal Logic (Energy Balance)
        def soc_logic_rule(m, t):
            return m.soc[t+1] == m.soc[t] * (1 - self.bess.self_discharge) + \
                                (m.p_pv2bess[t] * self.bess.ch_eff) - \
                                (m.p_bess2load[t] / self.bess.dis_eff)
        model.soc_logic = pyo.Constraint(model.t, rule=soc_logic_rule)
        

        #Grid Outage Constraints
        def outage_import_rule(m, t):
            return m.p_grid2load[t] <= self.grid_status[t] * max(load_data)
        model.outage_import = pyo.Constraint(model.t, rule=outage_import_rule)

        def outage_export_rule(m, t):
            return m.p_pv2grid[t] <= self.grid_status[t] * max(pv_gen_data)
        model.outage_export = pyo.Constraint(model.t, rule=outage_export_rule)
        


        ############### SOLVE #############

        solver = SolverFactory(self.cfg["solver"].lower()) 
        solver.options["MIPGap"] = 0.0        # Relative gap to zero
        solver.options["MIPGapAbs"] = 0.0       # Absolute gap to zero (crucial for large objectives)
        solver.options["TimeLimit"] = 300       # Give it more time (10 mins) to prove optimality
        solver.options["MIPFocus"] = 2          # Focus 2 = Focus on proving the OPTIMAL (Focus 1 is just finding any feasible)
        solver.options["Presolve"] = 2          # Aggressive presolve
        solver.options["NumericFocus"] = 2      # Increase numerical precision (prevents rounding errors)       
        results = solver.solve(model, tee=False)

        self.model = model
        acceptable_conditions = {
            TerminationCondition.optimal,
            TerminationCondition.feasible,
            TerminationCondition.maxTimeLimit
        }

        if (results.solver.status == SolverStatus.ok) and (results.solver.termination_condition == TerminationCondition.optimal):   
            total_imported_kwh = sum(pyo.value(model.p_grid2load[t]) for t in model.t)
            total_demand_kwh = sum(load_data)
            total_pv_kwh = sum(pv_gen_data) 
            total_pv_used_locally = sum(pyo.value(model.p_pv2load[t] + model.p_pv2bess[t]) for t in model.t)
            ss = 1 - total_imported_kwh / total_demand_kwh if total_demand_kwh > 0 else 0
            sc = total_pv_used_locally / total_pv_kwh if total_pv_kwh > 0 else 0
            sf = total_pv_kwh / total_demand_kwh if total_demand_kwh > 0 else 0
            total_wheeling_cost = sum(pyo.value(model.p_pv2load[t] + model.p_bess2load[t]) for t in model.t) * (self.cfg["wheeling_charge"] + self.cfg["re_levy"])
            total_import_cost = (total_imported_kwh * (self.cfg["grid_price"]))
            total_export_revenue = sum((pyo.value(model.p_pv2grid[t]) * (1 - 0.0496)) * self.cfg["feed_in_tariff"] for t in model.t)
            net_opex = total_import_cost + total_wheeling_cost - total_export_revenue
            avoided_cost = (total_pv_used_locally * (self.cfg["grid_price"]) - total_wheeling_cost)

            return {
                "ss": ss,
                "sc": sc,
                "sf": sf, 
                "total_unmet_kwh": total_imported_kwh, # Keeping this key name so MOPSO doesn't break
                "op_cost": net_opex - total_wheeling_cost,
                "served_kwh": total_demand_kwh - total_imported_kwh, 
                "avoided_cost": avoided_cost,
                "total_revenue": total_export_revenue,
                "pv2load": [pyo.value(model.p_pv2load[t]) for t in model.t],
                "pv2bess": [pyo.value(model.p_pv2bess[t]) for t in model.t],
                "pv2grid_actual": [pyo.value(model.p_pv2grid[t]) * (1 - 0.0496) for t in model.t], # Successful exports only
                "pv_curtailment": [
                    (pv_gen_data[t] - pyo.value(model.p_pv2load[t] + model.p_pv2bess[t] + model.p_pv2grid[t])) + # Unused PV
                    (pyo.value(model.p_pv2grid[t]) * 0.0496) # The 4.96% export loss
                    for t in model.t
                ],
                "bess2load": [pyo.value(model.p_bess2load[t]) for t in model.t],
                "grid2load": [pyo.value(model.p_grid2load[t]) for t in model.t],
                "unmet": [pyo.value(model.p_unmet[t]) for t in model.t]
            }
        else:
            total_demand_kwh = sum(load_data)
            empty = [0.0 for t in model.t]
            return {
                "ss": 0.0, "sc": 0.0, "sf": 0.0,
                "total_unmet_kwh": total_demand_kwh, "op_cost": 1e9, 
                "served_kwh" : 0.0, "avoided_cost": 0.0,
                "pv2load": empty, "pv2bess": empty, "pv2grid_actual": empty, 
                "pv_curtailment": empty, "bess2load": empty, "grid2load": empty, "unmet": empty
            }