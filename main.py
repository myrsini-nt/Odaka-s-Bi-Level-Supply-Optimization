import pandas as pd
import numpy as np
import matplotlib               
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import time
from config import PATHS, SITE, PV_panel, ARRAY, PV_system, BESS, LOAD, ECONOMICS, MOPSO as MOPSO_cfg, DISPATCH
from system_components import PVmodel, BESSmodel, Loadmodel
from mopso import MOPSO
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

def main():
    print("--- Initializing Energy System Bi-Level Optimization ---")
    start_time = time.time()

    # 1. Pre-load Static Data (The "Environment")
    # We do this once here to avoid file I/O bottlenecks in the optimization loop
    print("Loading TMY and Load profiles...")
    
    # Initialize the PV model once to generate the per-unit 8760 profile
    # We pass a dummy capacity of 1 just to get the normalized profile
    pv_base = PVmodel(PATHS, SITE, ARRAY, PV_panel, PV_system, pv_capacity_kwp=1.0)
    
    # Initialize the Load model
    load_base = Loadmodel(PATHS)
    
    print(f"Data loaded. Simulation horizon: {len(load_base.get_demand())} hours.")

    # 2. Initialize the Outer Loop (MOPSO)
    # We pass all config dictionaries and the pre-loaded objects
    optimizer = MOPSO(
        config_mopso = MOPSO_cfg,
        paths        = PATHS,
        site         = SITE,
        pv_panel     = PV_panel,
        array        = ARRAY,
        pv_system    = PV_system,
        bess_cfg     = BESS,
        load_cfg     = LOAD,
        dispatch_cfg = DISPATCH,
        pv_base_obj  = pv_base,    # Passing the pre-calculated profile
        load_base_obj= load_base,   # Passing the pre-loaded demand
        economics_cfg= ECONOMICS
    )

    # 3. Execute the Bi-Level Optimization
    print(f"Starting MOPSO: {MOPSO_cfg['n_particles']} particles, {MOPSO_cfg['n_iterations']} iterations.")
    print(f"Parallel workers: {MOPSO_cfg['n_jobs']} (using all available cores if -1)")
    
    pareto_archive = optimizer.run()

    # 4. Process and Save Results
    print("\n--- Optimization Complete ---")
    duration = (time.time() - start_time) / 60
    print(f"Total execution time: {duration:.2f} minutes")

    # Convert the Archive (Pareto Front) to a DataFrame
    # Each entry in the archive should contain: [PV_kwp, BESS_kwh, BESS_kw, Cost, Self_Sufficiency]
    results_df = pd.DataFrame(pareto_archive, columns=[
        "Cap_PV_kWp", 
        "Cap_BESS_kWh",  
        "Total_Annual_Cost_JPY", 
        "Self_Sufficiency_Fraction",
        "LCoE_JPY_kWh", 
        "CAPEX_JPY",
        "Avoided_Cost_JPY"
    ])
    results_df["Cap_BESS_kW"] = results_df["Cap_BESS_kWh"] * 0.25


    # Calculate Present Value Factor for an Annuity
    r = ECONOMICS.get("discount_rate", 0.04) 
    n = ECONOMICS.get("project_lifetime", 25)
    pv_factor = (1 - (1 + r)**-n) / r if r > 0 else n
    
    # Calculate NPV: (Annual Savings * PV Factor) - CAPEX
    results_df["NPV_JPY"] = (results_df["Avoided_Cost_JPY"] * pv_factor) - results_df["CAPEX_JPY"]
    
    # Calculate Simple Payback Period: CAPEX / Annual Savings
    # (Using np.where to prevent division by zero errors if savings are 0)
    results_df["Payback_Years"] = np.where(
        results_df["Avoided_Cost_JPY"] > 0,
        results_df["CAPEX_JPY"] / results_df["Avoided_Cost_JPY"],
        np.inf
    )

    # Save to the output path defined in config.py
    output_file = f"{PATHS['outputs']}/pareto_front_results.csv"
    results_df.to_csv(output_file, index=False)
    
    #knee point
    print("\nCalculating the optimal 'Knee Point' solution...")
    
    min_cost = results_df["Total_Annual_Cost_JPY"].min()
    max_cost = results_df["Total_Annual_Cost_JPY"].max()
    min_ss = results_df["Self_Sufficiency_Fraction"].min()
    max_ss = results_df["Self_Sufficiency_Fraction"].max()
    
    # Normalize so that 0 represents the "Utopia" (Best) value
    norm_cost = (results_df["Total_Annual_Cost_JPY"] - min_cost) / (max_cost - min_cost)
    norm_ss = (max_ss - results_df["Self_Sufficiency_Fraction"]) / (max_ss - min_ss)
    
    # Calculate Euclidean distance to the Utopia point (0, 0)
    distances = np.sqrt(norm_cost**2 + norm_ss**2)
    knee_idx = distances.idxmin()
    knee_solution = results_df.loc[knee_idx]
    
    print("\n*** OPTIMAL COMPROMISE SYSTEM (KNEE POINT) ***")
    print(f"PV Capacity:   {knee_solution['Cap_PV_kWp']:.2f} kWp")
    print(f"BESS Capacity: {knee_solution['Cap_BESS_kWh']:.2f} kWh / {knee_solution['Cap_BESS_kW']:.2f} kW")
    print(f"Total CAPEX:   ¥{knee_solution['CAPEX_JPY']:,.0f}")
    print(f"Annual Cost:   ¥{knee_solution['Total_Annual_Cost_JPY']:,.0f}")
    print(f"Self-Suff:     {knee_solution['Self_Sufficiency_Fraction']*100:.1f}%")
    print(f"LCoE:          ¥{knee_solution['LCoE_JPY_kWh']:.2f}/kWh")
    print(f"NPV:           ¥{knee_solution['NPV_JPY']:,.0f}")
    
    payback = knee_solution['Payback_Years']
    if payback <= n:
        print(f"Payback Period:{payback:.1f} Years")
    else:
        print("Payback Period:Exceeds project lifetime!")
    print("**********************************************\n")


    print(f"Final Pareto front saved to: {output_file}")
    print(f"Found {len(results_df)} non-dominated solutions.")

    plt.figure(figsize=(8, 6))

    plt.scatter(
        results_df["Total_Annual_Cost_JPY"],
        results_df["Self_Sufficiency_Fraction"],
        color='#426A80',      # Deep Slate Blue
        edgecolors='#2D3A40', # Charcoal Slate
        s=55,                 
        alpha=0.85,
        label='Pareto Optimal Systems'
    )
    
    # 2. Overlay the Knee Point as a distinct Rust Star
    plt.scatter(
        knee_solution["Total_Annual_Cost_JPY"],
        knee_solution["Self_Sufficiency_Fraction"],
        color='#AB664B',      # Rust 
        edgecolors='#2D3A40', 
        s=250,                # Make it large
        marker='*',           # Star shape
        zorder=5,             # Force it to draw on top of other points
        label='Knee Point'
    )
    plt.title("Pareto Front: Total Annual Cost vs. Self-Sufficiency", fontsize=14)
    plt.xlabel("Total Annual Cost (JPY)", fontsize=12)
    plt.ylabel("Self-Sufficiency Fraction (0 to 1)", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend(loc='lower right')

    plot_file = f"{PATHS['outputs']}/pareto_front_plot.png"
    plt.tight_layout()
    plt.savefig(plot_file, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {plot_file}")
    plt.show()
    
if __name__ == "__main__":
    # Standard Python entry point
    main()