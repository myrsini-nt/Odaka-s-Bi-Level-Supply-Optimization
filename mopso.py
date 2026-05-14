import numpy as np
import copy
import os
import pandas as pd
import matplotlib   
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from concurrent.futures import ProcessPoolExecutor
from system_components import PVmodel, BESSmodel, Loadmodel
from dispatch_02 import DispatchOptimizer
import config
from cycler import cycler

thesis_palette = [
    '#2D3A40', # 1. Charcoal Slate
    '#426A80', # 2. Deep Slate Blue
    '#89B3C7', # 3. Medium Steel Blue
    '#95ACB2', # 4. Grey-Blue
    '#DAE8F1', # 5. Pale Sky Blue
    '#DFDEE0', # 6. Parchment Beige
    '#E0D1B9', # 7. Sand Tan
    '#F8DBB1', # 8. Peach
    '#AB664B'  # 9. Rust
]
plt.rcParams['axes.prop_cycle'] = cycler(color=thesis_palette)

def plot_pareto_progress(archive, iteration, output_folder="Pareto_Progress"):
    """Saves a snapshot of the Pareto front during optimization."""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        
    tac_values = [a['fit'][0] for a in archive]
    ss_values = [a['fit'][1] for a in archive]
        
    plt.figure(figsize=(8, 6))
    plt.scatter(tac_values, ss_values, color='#426A80', edgecolors='#2D3A40', alpha=0.8)
    plt.title(f"MOPSO Pareto Front - Iteration {iteration+1}", fontsize=14, fontweight='bold')
    plt.xlabel("Total Annual Cost (JPY)", fontsize=12)
    plt.ylabel("Self-Sufficiency Ratio", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.4)
    
    filename = os.path.join(output_folder, f"pareto_iter_{iteration+1:03d}.png")
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()

def save_pareto_csv(archive, iteration, output_folder):
    """Saves the current Pareto archive solutions to a CSV file."""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        
    data = []
    for sol in archive:
        # Combine position [PV, BESS] and fitness [TAC, SS, LCoE, CAPEX, Avoided]
        row = list(sol['pos']) + list(sol['fit']) + list(sol['tracking'])
        data.append(row)
        
    df = pd.DataFrame(data, columns=[
        "Cap_PV_kWp", 
        "Cap_BESS_kWh", 
        "Rate_BESS_kW", 
        "Total_Annual_Cost_JPY", 
        "Self_Sufficiency_Fraction",
        "LCoE_JPY_kWh", 
        "CAPEX_JPY",
        "NPV_JPY",
        "Payback_Years"
    ])
    
    filename = os.path.join(output_folder, f"pareto_iter_{iteration+1:03d}.csv")
    df.to_csv(filename, index=False)

class Particle:
    def __init__(self, bounds):
        self.bounds = bounds
        # Position: [PV_kwp, BESS_kwh, bess_kw]
        self.position = np.array([np.random.uniform(b[0], b[1]) for b in bounds])
        self.velocity = np.zeros(len(bounds))
        self.best_pos = copy.deepcopy(self.position)
        self.fitness          = [float('inf'), 0.0]
        self.best_pos_fitness = [float('inf'), 0.0]
        self.tracking         = [float('inf'), float('inf'), -float('inf'), float('inf')]
class MOPSO:
    def __init__(self, config_mopso, paths, site, pv_panel, array, pv_system, bess_cfg, load_cfg, dispatch_cfg, pv_base_obj, load_base_obj, economics_cfg):
        self.cfg = config_mopso
        self.bounds = [self.cfg["bounds"]["C_PV_kwp"], 
                       self.cfg["bounds"]["E_BESS_kwh"],
                       self.cfg["bounds"]["P_BESS_kw"]]
        
        # Load static data once to share across particles
        self.paths = paths
        self.site = site
        self.pv_panel = pv_panel
        self.array = array
        self.pv_system = pv_system
        self.bess_cfg = bess_cfg
        self.load_cfg = load_cfg
        self.dispatch_cfg = dispatch_cfg
        self.pv_base_obj = pv_base_obj
        self.load_base_obj = load_base_obj
        self.economics_cfg = economics_cfg
    
        self.swarm = [Particle(self.bounds) for _ in range(self.cfg["n_particles"])]
        self.archive = [] # Pareto Front

    def _evaluate_particle(self, pos):
        """The bridge between the Outer Loop (PSO) and Inner Loop (Dispatch)"""
        pv_cap, bess_e, bess_p = pos
        bess_p = np.clip(bess_p, 0.25 * bess_e, 1.0 * bess_e)  # enforce 0.25C–1C
        #bess_p = bess_e * 0.50
        
        ######## Initialize Objects with candidate sizing #######
        self.pv_base_obj.pv_capacity_kwp = pv_cap
        bess = BESSmodel(bess_e, bess_p, self.bess_cfg, self.economics_cfg)


        ############ Run Inner Loop Dispatch ############ 
        dispatcher = DispatchOptimizer(self.pv_base_obj, bess, self.load_base_obj, self.dispatch_cfg)
        res = dispatcher.solve()
        annual_throughput_kwh = (sum(res["pv2bess"]) + sum(res["bess2load"]))
        op_cost_y1 = res["op_cost"]
        avoided_y1 = res["avoided_cost"]

        ############ Calculate Objectives ############ 

        # Obj 1: Total Annual Cost (Annualized CAPEX + OPEX)
        # Note: pv_cap is used here for its specific sizing cost
        r = config.ECONOMICS["discount_rate"] 
        n = config.ECONOMICS["project_lifetime"]
        i = config.ECONOMICS["inflation_rate"]

        crf = (r * (1 + r)**n) / ((1 + r)**n - 1) if r > 0 else 1/n
        capex_total = (bess.capex_total_jpy) + (pv_cap * self.pv_system["CAPEX_pv_jpy_kwp"]) 

        #include battery degradation
        cycle_life = self.bess_cfg["cycle_life"] * self.bess_cfg["dod_ref"]
        eol = self.bess_cfg["eol"]
        annual_fade = self.bess_cfg["calendar_fade_per_year"]
        
        #calculate equivalent full cycles - we are operating at 80% dod
        efc_year = annual_throughput_kwh / (2 * bess_e) if bess_e > 0 else 0

        soh = 1.0
        replacement_years = []
        for y in range(1, n + 1):
            soh -= (efc_year / cycle_life) + annual_fade
            soh = max(soh, 0.0)
            if soh <= eol:
                if y < n: 
                    replacement_years.append(y)
                soh = 1.0 #resets state of health as new bess is installed
        
        #multi-year npv cashflow loop 
        npv = -capex_total
        total_disc_opex = 0.0
        total_disc_energy = 0.0
        opex_base = pv_cap * self.pv_system["OPEX_pv_jpy_kwp"] +bess_e * self.bess_cfg["opex_kwh_yr"] 

        last_repl_cost = 0.0
        for y in range(1, n + 1):
            discount = (1 + r) ** y 
            opex_y = opex_base * (1 + i) ** (y - 1)
            avoided_y = avoided_y1 * (1 + i) ** (y - 1)
            
            repl_cost_y = 0.0
            if y in replacement_years:
                repl_cost_y = (bess_e * self.bess_cfg["replacement_cost_kwh"]) * (1 + i) ** y
                salvage = bess.capex_total_jpy * self.bess_cfg["salvage_fraction"] / discount
                repl_cost_y -= salvage
                last_repl_cost = repl_cost_y
            
            #annual cashflow 
            cf_y = avoided_y - opex_y - repl_cost_y
            npv += cf_y / discount

            total_disc_opex += opex_y / discount
            total_disc_energy += res["served_kwh"] / discount
        
        capex_annual = capex_total * crf
        repl_present_value = sum((bess_e * self.bess_cfg["replacement_cost_kwh"]) * (1 + i) ** y / (1 + r) ** y - bess.capex_total_jpy * self.bess_cfg["salvage_fraction"] / (1 + r) ** y   for y in replacement_years)
        tac = capex_annual + opex_base + repl_present_value * crf


        # Obj 2: Self-Sufficiency (We use 1-SS if the optimizer is a minimizer)
        ss = res["ss"]

        # tracking served demand and lcoe 
        served_kwh = res["served_kwh"]
        total_disc_cost = capex_total + total_disc_opex + repl_present_value 
        lcoe = total_disc_cost / total_disc_energy if total_disc_energy > 0 else float('inf')

        cumulative = -capex_total
        payback_year = n

        for y in range(1, n + 1):
            opex_y    = opex_base * (1 + i) ** (y - 1)
            avoided_y = avoided_y1 * (1 + i) ** (y - 1)
            repl_cost_y = 0.0
            if y in replacement_years:
                repl_cost_y = ((bess_e * self.bess_cfg["replacement_cost_kwh"]) * (1 + i) ** y - bess.capex_total_jpy * self.bess_cfg["salvage_fraction"] / (1 + r) ** y )
            cumulative += (avoided_y - opex_y - repl_cost_y) / discount # every year, not just replacement
            if cumulative >= 0 and payback_year == n:
                payback_year = y
                break

        return {
            "fitness": [tac, ss],
            "tracking": [lcoe, capex_total, npv, payback_year]
        }

    def update_archive(self):
        """Maintains the Pareto Front"""
        candidate_solutions = [{'pos': p.position.copy(), 'fit': p.fitness.copy(), 'tracking': p.tracking.copy()} for p in self.swarm] + self.archive
        new_archive = []
        
        for i, sol1 in enumerate(candidate_solutions):
            f1 = sol1['fit']
            dominated = False
            for j, sol2 in enumerate(candidate_solutions):
                # Pareto Dominance: Cost (f[0]) lower is better, SS (f[1]) higher is better
                if i == j: continue
                f2 = sol2['fit']
                if (f2[0] <= f1[0] and f2[1] >= f1[1]) and (f2[0] < f1[0] or f2[1] > f1[1]):
                    dominated = True
                    break
            if not dominated:
                is_duplicate = any(np.allclose(a['pos'], sol1['pos']) for a in new_archive)
                if not is_duplicate:
                    new_archive.append(sol1)
        
        # Limit archive size based on config
        self.archive = new_archive[:self.cfg["archive_size"]]

    def run(self):
        for it in range(self.cfg["n_iterations"]):
            # Parallel execution of the inner loop
            with ProcessPoolExecutor() as executor:
                positions = [p.position for p in self.swarm]
                results = list(executor.map(self._evaluate_particle, positions))
            
            for i, p in enumerate(self.swarm):
                p.fitness = results[i]["fitness"]
                p.tracking = results[i]["tracking"]
                # Update personal best
                f_new, f_old = p.fitness, p.best_pos_fitness
                old_dominates_new = (f_old[0] <= f_new[0] and f_old[1] >= f_new[1]) and \
                                    (f_old[0] < f_new[0] or f_old[1] > f_new[1])
                if not old_dominates_new:
                    p.best_pos = copy.deepcopy(p.position)
                    p.best_pos_fitness = copy.deepcopy(p.fitness)

            self.update_archive()
            print(f"Iteration {it+1}/{self.cfg['n_iterations']} complete. Pareto archive size: {len(self.archive)}")
            if (it % 10 == 0) or (it == self.cfg["n_iterations"] - 1):
                if len(self.archive) > 0:
                    plot_pareto_progress(self.archive, it, output_folder=self.paths['outputs'])
                    save_pareto_csv(self.archive, it, output_folder=self.paths['outputs'])
            # Update Velocity and Position
            w = self.cfg["w_start"] - (it/self.cfg["n_iterations"]) * (self.cfg["w_start"] - self.cfg["w_end"])
            for p in self.swarm:
                if len(self.archive) == 0:
                    continue 

                leader = self.archive[np.random.randint(len(self.archive))] # Select random leader from Pareto
                r1, r2 = np.random.rand(), np.random.rand()
                
                p.velocity = (w * p.velocity + 
                              self.cfg["c1"] * r1 * (p.best_pos - p.position) + 
                              self.cfg["c2"] * r2 * (leader['pos'] - p.position))
                
                p.position = np.clip(p.position + p.velocity, [b[0] for b in self.bounds], [b[1] for b in self.bounds])
        
        output_archive = [list(a['pos']) + list(a['fit']) + list(a['tracking'])  for a in self.archive]
        return output_archive