"""Optional Frigate MQTT-to-OpenRetail bridge; run only when configured.
Requires: pip install paho-mqtt>=2,<3 ; Frigate broker address and working broker.
"""
import json
import os
import httpx
from dotenv import load_dotenv
load_dotenv()

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
            if payload.get('type') not in ('new','end'):return
            event=payload.get('after') or payload.get('before') or {}
            if event.get('label')!='person':return
            r=httpx.post(endpoint,headers={'X-Integration-Key':key},json=payload,timeout=4)
            r.raise_for_status()
            print('Frigate event:',r.json())
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
