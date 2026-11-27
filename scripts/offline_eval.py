"""独立离线评估：不启动、不连接在线 MCP Host。
输入 CSV 必须含 label,risk_score 两列；label 为 0/1。
"""
import argparse, csv

def evaluate(path, threshold):
    rows=list(csv.DictReader(open(path,encoding='utf-8-sig')))
    if not rows: raise SystemExit('CSV 无评估记录')
    tp=fp=tn=fn=0
    for r in rows:
        y=int(r['label']); pred=float(r['risk_score'])>=threshold
        if y and pred: tp+=1
        elif not y and pred: fp+=1
        elif not y: tn+=1
        else: fn+=1
    return {'count':len(rows),'threshold':threshold,'tp':tp,'fp':fp,'tn':tn,'fn':fn,'sensitivity':round(tp/(tp+fn),4) if tp+fn else None,'specificity':round(tn/(tn+fp),4) if tn+fp else None,'false_positive_rate':round(fp/(fp+tn),4) if fp+tn else None}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('csv');p.add_argument('--threshold',type=float,default=55);a=p.parse_args();print(evaluate(a.csv,a.threshold))
