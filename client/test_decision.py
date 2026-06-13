import os, json
from datetime import datetime
import importlib.util

module_path = os.path.join(os.path.dirname(__file__), "gradio_app.py")
spec = importlib.util.spec_from_file_location("gradio_app", module_path)
gr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gr)

respond = gr.respond

# First interaction: time query
out_txt, out_hist, decision1, rationale1 = respond("what time is it?", [])
# Second interaction: volunteering query
out_txt2, out_hist2, decision2, rationale2 = respond("I want volunteering ideas in my town", out_hist)

os.makedirs("logs", exist_ok=True)
logpath = os.path.join("logs","decision_log.jsonl")
with open(logpath, "a", encoding="utf-8") as f:
    entry1 = {"ts": datetime.utcnow().isoformat()+"Z", "user_input": "what time is it?", "decision": decision1, "rationale": rationale1}
    f.write(json.dumps(entry1, ensure_ascii=False)+"\n")
    entry2 = {"ts": datetime.utcnow().isoformat()+"Z", "user_input": "I want volunteering ideas in my town", "decision": decision2, "rationale": rationale2}
    f.write(json.dumps(entry2, ensure_ascii=False)+"\n")

print("Logged decisions to", logpath)
print(entry1)
print(entry2)
