from pathlib import Path
import json
from balatro_agent.contract import Observation
from balatro_agent.actions import ActionRequest
from balatro_agent.notes import WriteNoteRequest
from balatro_agent.calculate import OPERATIONS
from balatro_agent.run_plan import PlanWrite

ROOT=Path(__file__).resolve().parents[1]
(ROOT/'docs/balatro-ai/observation-schema.json').write_text(json.dumps(Observation.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Observation JSON Schema exported.')
(ROOT/'docs/balatro-ai/action-schema.json').write_text(json.dumps(ActionRequest.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Action JSON Schema exported. Additional per-action rules are enforced by ActionRequest validators.')
(ROOT/'docs/balatro-ai/notes-schema.json').write_text(json.dumps(WriteNoteRequest.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
calculation_schema = {'title':'CalculateRequest','type':'object','additionalProperties':False,'required':['operation','inputs'],
    'properties':{'operation':{'type':'string','enum':list(OPERATIONS)}, 'inputs':{'oneOf':[
        {'type':'object','additionalProperties':False,'required':['values'],'properties':{'values':{'type':'array','minItems':1,'maxItems':200,'items':{'type':'number','minimum':-1e12,'maximum':1e12}}}},
        {'type':'object','additionalProperties':False,'required':['n','k'],'properties':{key:{'type':'integer','minimum':0,'maximum':1000} for key in ('n','k')}},
        {'type':'object','additionalProperties':False,'required':['population','successes','draws','min_successes','max_successes'],'properties':{key:{'type':'integer','minimum':0,'maximum':1000} for key in ('population','successes','draws','min_successes','max_successes')}}]}}}
(ROOT/'docs/balatro-ai/calculation-schema.json').write_text(json.dumps(calculation_schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Notes and calculation JSON Schemas exported; cross-field constraints are enforced by the tools.')
(ROOT/'docs/balatro-ai/run-plan-schema.json').write_text(json.dumps(PlanWrite.model_json_schema(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Run plan write schema exported; UTF-8 size, read references and live scope are validated by the tool.')
