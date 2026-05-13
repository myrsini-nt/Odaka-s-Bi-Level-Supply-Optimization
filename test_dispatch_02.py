from config import PATHS, SITE, PV_panel, ARRAY, PV_system, DISPATCH, BESS, ECONOMICS
from system_components import PVmodel, BESSmodel, Loadmodel
from dispatch_02 import DispatchOptimizer
import pyomo.environ as pyo
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.sankey import Sankey
import numpy as np
from cycler import cycler

thesis_palette = [
    '#AB664B', #0
    '#F8DBB1', #1
    '#F2C879', #2
    '#89B3C7', #3
    '#426A80', #4
    '#2D3A40', #5
    '#89B3C7', #6
    '#95ACB2', #7
    '#DAE8F1', #8
    '#DFDEE0', #9
    '#E0D1B9',  #10
    '#C9A46A',  # dusty mustard
   
]
plt.rcParams['axes.prop_cycle'] = cycler(color=thesis_palette)
from matplotlib.sankey import Sankey
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import PathPatch

def plot_annual_sankey(res_dict, load_data, pv_gen_data):
    from matplotlib.path import Path
    from matplotlib.patches import FancyBboxPatch
    import matplotlib.patches as mpatches

    # --- Aggregate annual totals ---
    pv2load   = sum(res_dict["pv2load"])        / 1000
    pv2bess   = sum(res_dict["pv2bess"])        / 1000
    pv2grid   = sum(res_dict["pv2grid_actual"]) / 1000
    curtail   = sum(res_dict["pv_curtailment"]) / 1000
    bess2load = sum(res_dict["bess2load"])       / 1000
    grid2load = sum(res_dict["grid2load"])       / 1000
    total_pv     = sum(pv_gen_data) / 1000
    total_demand = sum(load_data)   / 1000
    bess_losses  = pv2bess - bess2load

    # --- Scale: max band width in axes units ---
    MAX_W = 0.07
    scale = MAX_W / total_pv

    # --- Figure ---
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.set_title("Annual Energy Flow — System Sankey", fontsize=14,
                 fontweight='bold', pad=16)

    # ── Node definitions (cx, cy, w, h) ────────────────────────────────────
    nodes = {
        "pv":     (0.20, 0.72, 0.16, 0.11),
        "bess":   (0.20, 0.32, 0.16, 0.11),
        "grid":   (0.76, 0.72, 0.16, 0.11),
        "demand": (0.76, 0.32, 0.16, 0.11),
    }
    node_colors = {
        "pv":     thesis_palette[2],
        "bess":   thesis_palette[1],
        "grid":   thesis_palette[3],
        "demand": thesis_palette[5],
    }
    node_labels = {
        "pv":     ("PV Generation", f"{total_pv:.0f} MWh"),
        "bess":   ("BESS", f"▲ {pv2bess:.0f}  ▼ {bess2load:.0f} MWh"),
        "grid":   ("Grid", f"▲ {pv2grid:.0f} exp  ▼ {grid2load:.0f} imp MWh"),
        "demand": ("Load Demand", f"{total_demand:.0f} MWh"),
    }

    # ── Draw nodes ──────────────────────────────────────────────────────────
    def draw_node(name):
        cx, cy, w, h = nodes[name]
        box = FancyBboxPatch(
            (cx - w/2, cy - h/2), w, h,
            boxstyle="round,pad=0.01",
            facecolor=node_colors[name],
            edgecolor='white', linewidth=1.5,
            alpha=0.92, zorder=3
        )
        ax.add_patch(box)
        title, subtitle = node_labels[name]
        txt_color = 'white' if name in ('grid', 'demand') else '#2D3A40'
        ax.text(cx, cy + 0.018, title, ha='center', va='center',
                fontsize=10, fontweight='bold', color=txt_color, zorder=4)
        ax.text(cx, cy - 0.022, subtitle, ha='center', va='center',
                fontsize=8, color=txt_color, zorder=4)

    for name in nodes:
        draw_node(name)

    # ── Node edge coordinates ───────────────────────────────────────────────
    def nx(n): return nodes[n][0]
    def ny(n): return nodes[n][1]
    def nw(n): return nodes[n][2]
    def nh(n): return nodes[n][3]

    pv_right   = nx("pv")   + nw("pv")/2
    pv_left    = nx("pv")   - nw("pv")/2
    pv_top     = ny("pv")   + nh("pv")/2
    pv_bot     = ny("pv")   - nh("pv")/2
    pv_cx      = nx("pv")

    bess_right = nx("bess") + nw("bess")/2
    bess_top   = ny("bess") + nh("bess")/2
    bess_bot   = ny("bess") - nh("bess")/2
    bess_cx    = nx("bess")

    grid_left  = nx("grid") - nw("grid")/2
    grid_bot   = ny("grid") - nh("grid")/2
    grid_cx    = nx("grid")

    demand_left = nx("demand") - nw("demand")/2
    demand_top  = ny("demand") + nh("demand")/2
    demand_cx   = nx("demand")

    # ── Flow drawing function ───────────────────────────────────────────────
    def draw_flow(x0, y0, x1, y1, value, color, label=None, label_x=None, label_y=None):
        w = max(value * scale, 0.004)
        mx = (x0 + x1) / 2

        verts = [
            (x0, y0 + w/2), (mx, y0 + w/2), (mx, y1 + w/2), (x1, y1 + w/2),
            (x1, y1 - w/2), (mx, y1 - w/2), (mx, y0 - w/2), (x0, y0 - w/2),
            (x0, y0 + w/2),
        ]
        codes = [
            Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
            Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
            Path.CLOSEPOLY,
        ]
        patch = mpatches.PathPatch(
            Path(verts, codes),
            facecolor=color, edgecolor='white',
            linewidth=0.4, alpha=0.65, zorder=2
        )
        ax.add_patch(patch)

        if label:
            lx = label_x if label_x is not None else mx
            ly = label_y if label_y is not None else (y0 + y1) / 2
            ax.text(lx, ly, f"{label}\n{value:.0f} MWh",
                    ha='center', va='center', fontsize=7.5,
                    color='#2D3A40', zorder=5,
                    bbox=dict(facecolor='white', edgecolor='none',
                              alpha=0.75, pad=1.5, boxstyle='round'))

    # ── PV → Grid export ────────────────────────────────────────────────────
    # Exits upper-right of PV, enters upper-left of Grid (horizontal)
    draw_flow(
        pv_right,  ny("pv") + 0.02,
        grid_left, ny("grid") + 0.02,
        pv2grid, thesis_palette[4],
        label="Export",
        label_x=0.48, label_y=ny("pv") + 0.06
    )

    # ── PV → Load ───────────────────────────────────────────────────────────
    # Exits lower-right of PV, enters upper-left of Demand (diagonal)
    draw_flow(
        pv_right,    ny("pv") - 0.02,
        demand_left, ny("demand") + 0.02,
        pv2load, thesis_palette[2],
        label="PV→Load",
        label_x=0.48, label_y=0.56
    )

    # ── PV → BESS charge ────────────────────────────────────────────────────
    # Exits bottom-left of PV, enters top of BESS (vertical)
    draw_flow(
        pv_cx - 0.02, pv_bot,
        bess_cx - 0.02, bess_top,
        pv2bess, thesis_palette[1],
        label="Charge",
        label_x=pv_cx - 0.12, label_y=(pv_bot + bess_top) / 2
    )

    # ── PV → Curtailment ────────────────────────────────────────────────────
    # Exits top of PV upward to dead end
    draw_flow(
        pv_cx + 0.03, pv_top,
        pv_cx + 0.03, pv_top + 0.11,
        curtail, thesis_palette[10],
        label="Curtailed",
        label_x=pv_cx + 0.12, label_y=pv_top + 0.055
    )

    # ── BESS → Load discharge ───────────────────────────────────────────────
    # Exits right of BESS, enters lower-left of Demand (horizontal)
    draw_flow(
        bess_right,  ny("bess") + 0.01,
        demand_left, ny("demand") - 0.02,
        bess2load, thesis_palette[0],
        label="Discharge",
        label_x=0.48, label_y=ny("bess") - 0.01
    )

    # ── BESS losses ─────────────────────────────────────────────────────────
    # Exits bottom of BESS downward to dead end
    draw_flow(
        bess_cx + 0.02, bess_bot,
        bess_cx + 0.02, bess_bot - 0.10,
        bess_losses, thesis_palette[10],
        label="Losses",
        label_x=bess_cx + 0.11, label_y=bess_bot - 0.05
    )

    # ── Grid → Load import ──────────────────────────────────────────────────
    # Exits bottom of Grid, enters top of Demand (vertical)
    draw_flow(
        grid_cx + 0.02, grid_bot,
        demand_cx + 0.02, demand_top,
        grid2load, thesis_palette[3],
        label="Import",
        label_x=grid_cx + 0.11, label_y=(grid_bot + demand_top) / 2
    )

    # ── KPI strip ────────────────────────────────────────────────────────────
    ss = 1 - (grid2load / total_demand)
    sc = (pv2load + pv2bess) / total_pv
    sf = total_pv / total_demand
    kpi_text = (f"Self-Sufficiency: {ss:.1%}   |   "
                f"Self-Consumption: {sc:.1%}   |   "
                f"Solar Fraction: {sf:.1%}")
    fig.text(0.5, 0.01, kpi_text, ha='center', fontsize=10, color='#2D3A40',
             bbox=dict(boxstyle='round,pad=0.4', facecolor='#F1EFE8',
                       edgecolor='#B4B2A9', linewidth=0.8))

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor=thesis_palette[2],  alpha=0.7, label=f'PV to Load ({pv2load:.0f} MWh)'),
        mpatches.Patch(facecolor=thesis_palette[1],  alpha=0.7, label=f'PV to BESS — charge ({pv2bess:.0f} MWh)'),
        mpatches.Patch(facecolor=thesis_palette[4],  alpha=0.7, label=f'PV to Grid — export ({pv2grid:.0f} MWh)'),
        mpatches.Patch(facecolor=thesis_palette[0],  alpha=0.7, label=f'BESS to Load — discharge ({bess2load:.0f} MWh)'),
        mpatches.Patch(facecolor=thesis_palette[3],  alpha=0.7, label=f'Grid to Load — import ({grid2load:.0f} MWh)'),
        mpatches.Patch(facecolor=thesis_palette[10], alpha=0.7, label=f'Curtailment + Losses ({curtail + bess_losses:.0f} MWh)'),
    ]
    ax.legend(handles=legend_elements, loc='lower right',
              frameon=True, fontsize=8, framealpha=0.9)

    plt.tight_layout()
    plt.savefig("annual_energy_sankey.png", dpi=300, bbox_inches='tight')
    print("Saved: annual_energy_sankey.png")
    plt.show()



def plot_dispatch_results(model, res_dict, load_data, pv_gen_data, title, start_hour=0, end_hour=8760):
    t_range = range(start_hour, end_hour)
    
    pv2load  = res_dict["pv2load"][start_hour:end_hour]
    bess2load = res_dict["bess2load"][start_hour:end_hour]
    grid2load = res_dict["grid2load"][start_hour:end_hour]
    unmet    = res_dict["unmet"][start_hour:end_hour]
    pv2bess  = res_dict["pv2bess"][start_hour:end_hour]
    pv2grid  = res_dict["pv2grid_actual"][start_hour:end_hour]
    curtail  = res_dict["pv_curtailment"][start_hour:end_hour]
    soc      = [pyo.value(model.soc[t]) for t in t_range]
    load     = load_data[start_hour:end_hour]
    pv_total = pv_gen_data[start_hour:end_hour]

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True,
                                         gridspec_kw={'height_ratios': [2, 2, 1]})

    # --- Top Plot: LOAD SIDE — how is demand met? ---
    # Stack top should equal load profile line exactly
    ax1.stackplot(t_range, pv2load, bess2load, grid2load, unmet,
                  labels=['PV to Load', 'BESS Discharge', 'Grid Import', 'Unmet Demand'],
                  colors=[thesis_palette[2], thesis_palette[0], 
                          thesis_palette[3], thesis_palette[8]],
                  alpha=0.85)
    ax1.plot(t_range, load, color=thesis_palette[5], linestyle='--', 
             linewidth=1.5, label='Load Demand')
    ax1.set_ylabel('Power (kW)')
    ax1.set_title(f'{title} — Load Coverage')
    ax1.legend(loc='upper right', ncol=2, frameon=True, fontsize='small')

    # --- Middle Plot: PV SIDE — where does generation go? ---
    # Stack top should equal PV available line exactly
    ax2.stackplot(t_range, pv2load, pv2bess, pv2grid, curtail,
                  labels=['PV to Load', 'PV to BESS (Charge)', 
                          'PV to Grid (Export)', 'Curtailment/Loss'],
                  colors=[thesis_palette[2], thesis_palette[1], 
                          thesis_palette[4], thesis_palette[10]],
                  alpha=0.85)
    ax2.plot(t_range, pv_total, color=thesis_palette[11], linestyle='-',
             linewidth=1.5, alpha=0.9, label='Total PV Available')
    ax2.set_ylabel('Power (kW)')
    ax2.set_title(f'{title} — PV Allocation')
    ax2.legend(loc='upper right', ncol=2, frameon=True, fontsize='small')

    # --- Bottom Plot: Battery SOC ---
    ax3.fill_between(t_range, soc, color=thesis_palette[0], alpha=0.5, label='Battery SOC')
    ax3.set_ylabel('Storage (kWh)')
    ax3.set_xlabel('Hour of the Year')
    ax3.legend(loc='upper right')

    plt.tight_layout()
    file_name = title.lower().replace(" ", "_") + ".png"
    plt.savefig(file_name, dpi=300)
    print(f"Saved plot: {file_name}")
    plt.show()

def save_results_to_csv(results, model, load_data, pv_gen_data, filename="annual_dispatch_results.csv"):
    """
    Extracts hourly dispatch data and battery SOC to save into a CSV.
    """
    import pandas as pd
    import pyomo.environ as pyo
    
    T = len(load_data)
    
    # Consolidate all hourly streams
    data = {
        "Hour": range(T),
        "Load_Demand_kW": load_data,
        "PV_Available_kW": pv_gen_data,
        "PV_to_Load_kW": results["pv2load"],
        "PV_to_BESS_kW": results["pv2bess"],
        "PV_to_Grid_Actual_kW": results["pv2grid_actual"],
        "BESS_to_Load_kW": results["bess2load"],
        "Grid_to_Load_kW": results["grid2load"],
        "Unmet_Demand_kW": results["unmet"],
        "PV_Curtailment_Loss_kW": results["pv_curtailment"],
        "BESS_SOC_kWh": [pyo.value(model.soc[t]) for t in range(T)]
    }
    
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False)
    print(f"Success: Annual dispatch saved to {filename}")

def run_specific_case():
    # 1.Define test specific capacities
    pv_capacity_kwp = 1136.0 
    bess_energy_kwh = 100.0   
    bess_power_kw   = 50.0  
    
    print(f"Initializing system: PV={pv_capacity_kwp}kWp, BESS={bess_energy_kwh}kWh")

    # 2. Instantiate Components
    # Load profile first
    load_obj = Loadmodel(PATHS)
    
    # Initialize PV (this will perform the TMY/pvlib calculations for 1.9MWp)
    pv_obj = PVmodel(PATHS, SITE, ARRAY, PV_panel, PV_system, pv_capacity_kwp)
    normalized_df = pv_obj.per_unit_profile.to_frame(name="ac_output_per_kwp")
    output_path = "normalized_solar_profile.csv"
    normalized_df.to_csv(output_path)
    print(f"Normalized 8760 profile saved to {output_path}")

    # Initialize BESS
    bess_obj = BESSmodel(
    E_max_kwh=bess_energy_kwh, 
    P_max_kw=bess_power_kw, 
    BESS_CFG=BESS, 
    ECONOMICS=ECONOMICS
    )

    # 3. Initialize and Solve Dispatch
    optimizer = DispatchOptimizer(pv_obj, bess_obj, load_obj, DISPATCH)
    
    print("Solving annual dispatch (8760 hours)...")
    results = optimizer.solve()

    load_profile = load_obj.get_demand()[:8760]
    pv_raw = pv_obj.get_generation(pv_capacity_kwp)[:8760]
    pv_profile = np.nan_to_num(np.array(pv_raw), nan=0.0)


    # 4. Display Results
    print("\n--- Dispatch Results ---")
    print(f"Self-Sufficiency (SS):  {results['ss']*100:.2f}%")
    print(f"Self-Consumption (SC):  {results['sc']*100:.2f}%")
    print(f"Solar Fraction (SF):    {results['sf']*100:.2f}%")
    print(f"Total Grid Imports:     {results['total_unmet_kwh']:.2f} kWh")
    print(f"Total Annual OPEX:      {results['op_cost']:.2f} JPY")
    print(f"Total Avoided Cost:     {results['avoided_cost']:.2f} JPY")
    print(f"Total Exports:          {results['total_revenue']:.2f} JPY")
    save_results_to_csv(results, optimizer.model, load_profile, pv_profile)
    
    # Plots 
    print("\n--- Generating Visualization Plots ---")
    # Annual
    # In your main script, after solver returns results:
    plot_annual_sankey(results, load_profile, pv_profile) 
    plot_dispatch_results(optimizer.model, results, load_profile, pv_profile, "Annual Energy Dispatch")
    
    # Summer Week (July)
    plot_dispatch_results(optimizer.model, results, load_profile, pv_profile, "Representative Summer Week", start_hour=4344, end_hour=4512)
    
    # Winter Week (January)
    plot_dispatch_results(optimizer.model, results, load_profile, pv_profile, "Representative Winter Week", start_hour=0, end_hour=168)

if __name__ == "__main__":
    run_specific_case()