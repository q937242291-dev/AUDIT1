"""Create Figures 3-8 from recomputed tables; extract illustrations 1-2.

Regenerated plots preserve the empirical estimands, not the manuscript layout.
The recorded manuscript is immutable. Figure notes identify the estimands.
"""
from __future__ import annotations
import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

COLORS=['#246787','#df8c32','#4b9165','#aa5276','#8071ae','#879ca8','#654e40']

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def values(rows,key,scale=1):return [float(r[key])*scale for r in rows]
def save(fig,path):
    fig.savefig(path.with_suffix('.pdf'),bbox_inches='tight',metadata={'Creator':'AUDIT reproducibility package','Author':'Anonymous','CreationDate':None,'ModDate':None})
    fig.savefig(path.with_suffix('.png'),bbox_inches='tight',dpi=180,metadata={'Software':'AUDIT reproducibility package'})
    plt.close(fig)
def clean(ax,title,ylabel=None):
    ax.set_title(title,loc='left',fontweight='bold',pad=12)
    if ylabel:ax.set_ylabel(ylabel)
    ax.spines[['top','right']].set_visible(False)
    ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
def labels(ax,names,rotation=25):ax.set_xticks(range(len(names)),names,rotation=rotation,ha='right' if rotation else 'center')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--results',type=Path)
    p.add_argument('--out',type=Path)
    a=p.parse_args();res=a.results or a.root/'reproduced';out=a.out or res/'figures';out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,'pdf.fonttype':42,'figure.constrained_layout.use':True})
    c=res/'controlled';obs=res/'observational';repair=res/'repair';model=res/'model_swap'
    prog=read(c/'table_02_progressive_context.csv');abl=read(c/'table_05_component_ablation.csv')
    effects=read(c/'table_04_paired_search_representation.csv');methods=read(c/'table_06_localization_methods.csv')
    projection=read(c/'table_07_input_projection.csv');context=read(c/'table_08_matched_context.csv')
    marginal=read(c/'figure_08_context_marginal_utility.csv');policy=read(c/'table_09_audit_policy.csv')
    replay=read(c/'table_11_history_replay.csv');timeline=read(c/'figure_07c_replay_checkpoints.csv')
    prevalence=read(obs/'figure3_process_prevalence.csv');rates=read(repair/'repair_endpoint_rates.csv')
    # Illustrations are source-page extracts, not empirical calculations or new evidence.
    from pypdf import PdfReader,PdfWriter
    manuscript=PdfReader(a.root/'paper/manuscript.pdf')
    for number,page_index,top,bottom in [(1,1,.114,.353),(2,3,.114,.357)]:
        page=manuscript.pages[page_index];width=float(page.mediabox.width);height=float(page.mediabox.height)
        page.cropbox.lower_left=(width*.09,height*(1-bottom));page.cropbox.upper_right=(width*.91,height*(1-top))
        writer=PdfWriter();writer.add_page(page);writer.add_metadata({'/Title':f'Manuscript Figure {number} — source extract','/Author':'Anonymous'})
        with (out/f'figure_{number:02d}_manuscript_illustration.pdf').open('wb') as f:writer.write(f)
    # Figure 3: success-conditioned process presence, not necessity.
    fig,ax=plt.subplots(figsize=(8.6,4.5));rows=list(reversed(prevalence))
    ax.barh(range(len(rows)),values(rows,'prevalence',100),color=[COLORS[0] if r['band']=='high' else COLORS[1] if r['band']=='intermediate' else COLORS[5] for r in rows])
    ax.set_yticks(range(len(rows)),[r['process_unit'].replace('_',' ') for r in rows]);ax.set_xlim(0,114)
    for i,r in enumerate(rows):ax.text(float(r['prevalence'])*100+1,i,f"{100*float(r['prevalence']):.1f}% ({r['k']})",va='center',fontsize=8)
    ax.set_xlabel('Successful trajectories with observed process unit (%)');clean(ax,'Figure 3. Process prevalence (n = 1,308)')
    save(fig,out/'figure_03_process_prevalence')
    # Figure 4: outcomes, deltas, completed ablations, full-cohort diagnostics.
    fig,axes=plt.subplots(2,2,figsize=(12,8));ax=axes[0,0];x=list(range(5))
    for key,label,color in [('file_hit_1','FileHit@1',COLORS[0]),('candidate_nonempty','Nonempty candidate',COLORS[1]),('evidence_record_complete','Recorded evidence complete',COLORS[2])]:ax.plot(x,values(prog,key,100),'o-',label=label,color=color)
    labels(ax,['Issue','Failure','Structure','Requirements','Bundle']);clean(ax,'(a) Progressive context: 240 runs / condition','Percent');ax.legend(fontsize=7)
    ax=axes[0,1];base=float(prog[0]['file_hit_1']);ax.bar(x,[(float(r['file_hit_1'])-base)*100 for r in prog],color=COLORS[0]);labels(ax,['Issue','Failure','Structure','Requirements','Bundle']);clean(ax,'(b) Change relative to issue-only','FileHit@1 change (percentage points)')
    ax=axes[1,0];ax.bar(range(9),values(abl,'file_hit_1',100),color=COLORS[0]);labels(ax,[r['label'].replace('- ','−') for r in abl],40);clean(ax,'(c) Completed-only component outcomes','FileHit@1 (%)')
    for i,r in enumerate(abl):ax.text(i,float(r['file_hit_1'])*100+.4,r['completed'],ha='center',fontsize=7)
    records=[json.loads(s) for s in (a.root/'data/logs/localization_methods/full_audit_localization/audit_verdicts.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    counts=defaultdict(Counter)
    for r in records:counts[r['agent_name']][r['verdict']]+=1
    diagnostic=[]
    for name,count in sorted(counts.items()):diagnostic.append(dict(agent=name,**{k:count[k] for k in ['pass','warn','fail']},n=sum(count.values())))
    with (out/'figure_04d_diagnostic_counts.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(diagnostic[0]));w.writeheader();w.writerows(diagnostic)
    ax=axes[1,1];bottom=[0]*len(diagnostic)
    for key,col in [('pass',COLORS[2]),('warn',COLORS[1]),('fail',COLORS[3])]:
        nums=[r[key] for r in diagnostic];ax.bar(range(len(nums)),nums,bottom=bottom,label=key,color=col);bottom=[a+b for a,b in zip(bottom,nums)]
    labels(ax,[r['agent'].replace('Agent','').replace('Auditor','').replace('Evidence','') for r in diagnostic],35);clean(ax,'(d) Separate diagnostic cohort: 260 tasks','Recorded verdicts');ax.legend(fontsize=7)
    save(fig,out/'figure_04_quality_and_necessity')
    # Figure 5: paired search/representation; method costs; projection; replay categories.
    fig,axes=plt.subplots(2,2,figsize=(11.8,8));ax=axes[0,0]
    for i,factor in enumerate(['Search','Representation']):
        rows=[r for r in effects if r['factor']==factor];ax.bar([j+(i-.5)*.36 for j in range(3)],values(rows,'delta',100),width=.36,label=factor,color=COLORS[i])
    labels(ax,['Hit@1','Hit@3','Hit@5'],0);clean(ax,'(a) Run-pair effects; repeated tasks retained','Change (percentage points)');ax.legend()
    ax=axes[0,1]
    for i,r in enumerate(methods):ax.scatter(float(r['mean_tokens']),float(r['file_hit_1'])*100,color=COLORS[i],s=55);ax.annotate(r['method'],(float(r['mean_tokens']),float(r['file_hit_1'])*100),xytext=(3,6),textcoords='offset points',fontsize=7)
    ax.set_xlim(0,max(values(methods,'mean_tokens'))*1.25);ax.set_xlabel('Mean recorded tokens');clean(ax,'(b) Localization methods (260 tasks)','FileHit@1 (%)')
    ax=axes[1,0];fields=['issue_visible','future_payload_visible','location_payload_visible','diff_payload_visible'];matrix=[[float(r[k]) for k in fields] for r in projection]
    ax.imshow(matrix,vmin=0,vmax=1,cmap='Blues',aspect='auto');ax.set_xticks(range(4),['Issue','Future','Location','Diff']);ax.set_yticks(range(5),['Original','Scrubbed','Legal history','Location only','Diff only']);ax.grid(False);ax.set_title('(c) Recorded input visibility: 6 tasks × 3 seeds',loc='left',fontweight='bold')
    for i,row in enumerate(matrix):
        for j,v in enumerate(row):ax.text(j,i,f'{v:.0%}',ha='center',va='center',color='white' if v>.5 else 'black')
    ax=axes[1,1];ax.barh(range(len(replay)),values(replay,'rows'),color=COLORS[5]);ax.set_yticks(range(len(replay)),[r['label'] for r in replay]);ax.invert_yaxis();clean(ax,'(d) Replay classification: 300 records');ax.set_xlabel('Task × branch × checkpoint records')
    save(fig,out/'figure_05_behavior_effects')
    # Figure 6 and 8 share one measured 40-task/7-condition cohort.
    short=['Issue','Entity','Symbol','Dependency','Structure','History','Full']
    fig,axes=plt.subplots(2,2,figsize=(11.6,7.8));ax=axes[0,0]
    for k,col in [(1,COLORS[0]),(3,COLORS[1]),(5,COLORS[2])]:ax.plot(range(7),values(context,f'file_hit_{k}',100),'o-',label=f'Hit@{k}',color=col)
    labels(ax,short);clean(ax,'(a) Matched localization outcomes','Percent');ax.legend()
    ax=axes[0,1];ax.bar(range(7),values(context,'mean_tokens'),color=COLORS[0]);labels(ax,short);clean(ax,'(b) Measured context cost','Mean tokens')
    ax=axes[1,0];ax.bar([i-.18 for i in range(7)],values(marginal,'gain_hit_1'),width=.36,label='Gains',color=COLORS[2]);ax.bar([i+.18 for i in range(7)],[-x for x in values(marginal,'loss_hit_1')],width=.36,label='Losses',color=COLORS[3]);labels(ax,short);clean(ax,'(c) Paired changes versus issue-only','Task count');ax.legend()
    ax=axes[1,1]
    for i,r in enumerate(context):ax.scatter(float(r['mean_tokens']),float(r['file_hit_1'])*100,s=55,color=COLORS[i]);ax.annotate(short[i],(float(r['mean_tokens']),float(r['file_hit_1'])*100),xytext=(4,5+(i%2)*4),textcoords='offset points',fontsize=8)
    ax.set_xlim(0,7200);ax.set_xlabel('Mean tokens');clean(ax,'(d) Cost–outcome frontier (Hit@1)','Percent')
    save(fig,out/'figure_06_matched_context')
    fig,axes=plt.subplots(2,2,figsize=(11.6,7.6));ax=axes[0,0]
    for i,r in enumerate(policy):ax.scatter(float(r['mean_tokens']),float(r['file_hit_1'])*100,s=55,color=COLORS[i],label=r['label'])
    ax.set_xlabel('Mean recorded tokens');clean(ax,'(a) Audit policies: 30 assignments / 14 issues','FileHit@1 (%)');ax.legend(fontsize=6,loc='lower left')
    ax=axes[0,1];slice_rows=read(model/'figure_07b_model_slices.csv')
    for i,m in enumerate(sorted({r['model'] for r in slice_rows})):
        rows=sorted([r for r in slice_rows if r['model']==m],key=lambda r:int(r['n']));ax.plot(values(rows,'n'),values(rows,'hit_1',100),'o-',label=m.replace('_','.'),color=COLORS[i])
    ax.set_xlabel('Source-defined CommonN slice (membership unverified)');clean(ax,'(b) Path-audit model swap only','FileHit@1 (%)');ax.legend(fontsize=7)
    ax=axes[1,0];ax.plot(values(timeline,'checkpoint_days'),values(timeline,'completion_rate',100),'o-',color=COLORS[0])
    for r in timeline:ax.annotate(f"{float(r['completion_rate'])*100:.1f}%",(float(r['checkpoint_days']),float(r['completion_rate'])*100),xytext=(4,5),textcoords='offset points',fontsize=8)
    ax.set_xlabel('Days after checkpoint origin');ax.set_ylim(0,70);clean(ax,'(c) Replay completion: corrected labels','Completion (%)')
    ax=axes[1,1];ax.bar(range(4),values(rates,'percent'),color=[COLORS[2],COLORS[0],COLORS[2],COLORS[0]])
    labels(ax,['Bounded\nGold','Bounded\nAgent','Official\nReference','Official\nAgent'],0);clean(ax,'(d) Separate repair endpoints','Rate (%)');ax.set_ylim(0,102)
    for i,r in enumerate(rates):ax.text(i,float(r['percent'])+2,f"{r['numerator']}/{r['denominator']}",ha='center')
    save(fig,out/'figure_07_robustness_and_repair')
    fig,axes=plt.subplots(1,3,figsize=(13,4.4));ax=axes[0]
    for k,col in [(1,COLORS[0]),(3,COLORS[1]),(5,COLORS[2])]:ax.plot(range(7),values(marginal,f'delta_hit_{k}',100),'o-',label=f'Hit@{k}',color=col)
    labels(ax,short,45);clean(ax,'(a) Paired marginal outcome','Change (percentage points)');ax.legend(fontsize=7)
    ax=axes[1];ax.bar(range(7),values(marginal,'delta_tokens'),color=COLORS[0]);labels(ax,short,45);clean(ax,'(b) Incremental cost','Tokens beyond issue-only')
    ax=axes[2]
    for i,r in enumerate(marginal):ax.scatter(float(r['delta_tokens']),float(r['delta_hit_1'])*100,s=55,color=COLORS[i]);ax.annotate(short[i],(float(r['delta_tokens']),float(r['delta_hit_1'])*100),xytext=(3,5+(i%2)*6),textcoords='offset points',fontsize=7)
    ax.set_xlim(-250,5600);ax.set_xlabel('Incremental tokens');clean(ax,'(c) Marginal cost versus benefit','Hit@1 change (percentage points)')
    save(fig,out/'figure_08_marginal_context_utility')
    notes={'figures_1_2':'Cropped manuscript illustrations; source data and editable artwork are not reconstructed by extraction.',
      'figure_3':'Success-conditioned trajectory prevalence; orientation zero is parser non-observation.',
      'figure_4c':'Completed-run denominator, aligned with Table 5; original scheduled-rate panel differs for two incomplete variants.',
      'figure_4d':'260-task diagnostic cohort, distinct from the Table 1 60-task same-ID different-run join.',
      'figure_5':'Projection is 6 distinct tasks × 3 seeds × 5 conditions. Table 4 effects are run-level and include repeated tasks.',
      'figure_7b':'Recomputed from 2400 recovered prediction rows. Only path-audit LLM varies; source slices not certified as benchmark release splits.',
      'figure_7c':'d7=34/60=56.7%; d30=23/60=38.3%; manuscript labels 56.5/38.2 are not retained.',
      'layout':'New data-driven layouts; panel placement and typography need not be pixel-identical to manuscript.'}
    (out/'figure_notes.json').write_text(json.dumps(notes,indent=2)+'\n',encoding='utf-8');print(json.dumps({'pdf_figures':8,'empirical_pngs':6,'directory':out.name}))
    return 0
if __name__=='__main__':raise SystemExit(main())
