"""Optional Frigate MQTT-to-OpenRetail bridge; run only when configured.
Requires: pip install paho-mqtt>=2,<3 ; Frigate broker address and working broker.
"""
import json
import os
import httpx
from dotenv import load_dotenv
load_dotenv()

FORWARDED_TYPES=('new','update','end')

def person_payload(payload):
    """Person new/update/end metadata only. None means do not forward. No broker is involved."""
    if not isinstance(payload,dict):return None
    if payload.get('type') not in FORWARDED_TYPES:return None
    event=payload.get('after') or payload.get('before') or {}
    if not isinstance(event,dict) or event.get('label')!='person':return None
    return payload

def forward_event(payload,post):
    body=person_payload(payload)
    if body is None:return {'forwarded':False}
    return {'forwarded':True,'response':post(body)}

def main():
    import paho.mqtt.client as mqtt
    endpoint=os.getenv('INTERNAL_API_URL','http://127.0.0.1:8000').rstrip('/')+'/api/integrations/frigate-event'
    key=os.environ['INTEGRATION_KEY']
    def on_connect(client,userdata,flags,reason_code,properties):
        if reason_code==0:client.subscribe('frigate/events',qos=1)
        else:print('MQTT connection rejected:',reason_code)
    def on_message(client,userdata,msg):
        try:
            if len(msg.payload)>128000:return
            payload=json.loads(msg.payload)
            outcome=forward_event(payload,lambda body:httpx.post(
                endpoint,headers={'X-Integration-Key':key},json=body,timeout=4))
            if not outcome['forwarded']:return
            outcome['response'].raise_for_status()
            print('Frigate event:',outcome['response'].json())
        except (ValueError,httpx.HTTPError) as exc:
            print('Event forwarding failed:',type(exc).__name__)
    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='openretail-frigate-bridge')
    username=os.getenv('FRIGATE_MQTT_USER')
    if username:c.username_pw_set(username,os.getenv('FRIGATE_MQTT_PASSWORD',''))
    c.on_connect=on_connect
    c.on_message=on_message
    c.connect(os.getenv('FRIGATE_MQTT_HOST','127.0.0.1'),int(os.getenv('FRIGATE_MQTT_PORT','1883')))
    c.loop_forever()

if __name__=='__main__':main()
