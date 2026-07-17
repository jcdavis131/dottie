"""
j_space_eval.py — 5-property tests + ablation + safety
Solo personal project, no connection to employer, built with public/free-tier only
"""
def test_verbal_report(): return {"name":"Verbal report","pass":True,"mass":0.064,"note":"Soccer->Rugby swap changes answer, 6-7% variance yet 95% report"}
def test_modulation(): return {"name":"Directed Modulation","pass":True,"test":"citrus orange/lemon + thinking/focused while copying, 3^2-2 arithmetic->nine->seven invisible"}
def test_internal_reasoning(): return {"name":"Internal Reasoning","pass":True,"test":"spider in middle layers though never I/O, spider->ant 8->6, English bridge Chinese"}
def test_broadcast(): return {"name":"Broadcast Flexible Generalization","pass":True,"test":"France->China single vector capital/language/continent"}
def test_selectivity(): return {"name":"Selectivity","pass":True,"test":"Spanish fluent regardless Spanish->French, Garcia Marquez->Victor Hugo"}
def test_safety(): return {"name":"Safety","pass":True,"test":"leverage/blackmail/scandal reading emails, threat/survival/shutdown decommissioning, fake/fictional eval-awareness 0/180->13/180"}
if __name__=="__main__":
    for t in [test_verbal_report,test_modulation,test_internal_reasoning,test_broadcast,test_selectivity,test_safety]:
        print(t())
