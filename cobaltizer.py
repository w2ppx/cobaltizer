import requests
import time
from flask import Flask, Response, request
import concurrent.futures, threading, re
app = Flask(__name__)

API_FRONTEND = 'https://instances.hyper.lol/'
MINIMAL_SCORE = 0
TIMEOUT = 0
UPDATE_INSTANCE_TIME = 0
DISABLE_UNSTABLE_INSTANCES = False
fastest_instance = None
instances_ping = {}
try:
    with open('.env', 'r') as file:
        for line in file:
            key, value = line.strip().split('=')
            if key == 'MINIMAL_SCORE':
                MINIMAL_SCORE = int(value) if value else 90
            elif key == 'TIMEOUT':
                TIMEOUT = int(value) if value else 5
            elif key == 'UPDATE_INSTANCE_TIME':
                UPDATE_INSTANCE_TIME = int(value) if value else 60
            elif key == 'DISABLE_UNSTABLE_INSTANCES':
                DISABLE_UNSTABLE_INSTANCES = bool(value) if value else True
            elif key == 'PORT':
                PORT = int(value) if value else 8080
except FileNotFoundError:
    print('No .env file found, please fill in the required fields')
    exit(1)


def ping_site(url):
    try:
        if not url.startswith('http'):
            url = 'http://' + url
        elapsed = time.time()
        with requests.Session() as session:
            response = session.get(url + '/api/serverInfo', timeout=TIMEOUT)
        return round(time.time() - elapsed, 3)
    except Exception as e:
        return None

def get_instances():
    url = API_FRONTEND + 'instances.json'   
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0'}) #cloudflare doesn't like the default user agent
    instances = [
        instance['api']
        for instance in response.json()
        if instance['score'] >= MINIMAL_SCORE
        and instance['api_online']
        and (instance['frontend_online'] if DISABLE_UNSTABLE_INSTANCES else True)
    ]
    return instances

def main():
    global fastest_instance
    elapsed = time.time()
    instances = get_instances()
    print('Updating instances...')
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(append_instances, instance) for instance in instances]
        concurrent.futures.wait(futures)
    print(f"Finished pinging {len(instances)} instances in {round(time.time() - elapsed, 3)} seconds")
    fastest_instance = min(instances_ping, key=instances_ping.get) if instances_ping else None

def append_instances(instance):
    ping = ping_site(instance)
    if ping is None:
        print(f"Failed to ping {instance}")
        return
    ping = int(ping * 1000)
    instances_ping[instance] = ping


@app.route('/<path:proxy_path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
def proxy(proxy_path):
    global fastest_instance
    if not fastest_instance:
        return "No available instances", 503
    fastest_instance = 'http://' + fastest_instance if not fastest_instance.startswith('http') else fastest_instance
    print(f"Proxying request to {fastest_instance}/{proxy_path}...")
    url = f"{fastest_instance}/{proxy_path}"

    headers = {key: value for (key, value) in request.headers if key != 'Host'}
    headers['Host'] = fastest_instance.split('//')[1]

    while True:
        headers.pop('User-Agent', None)
        response = requests.request(
            method=request.method,
            url=url,
            data=request.get_data(),
            headers=headers,
            allow_redirects=False
        )
        if response.status_code >= 400:
            instances_ping.pop(fastest_instance.split('//')[1], None)
            fastest_instance = min(instances_ping, key=instances_ping.get) if instances_ping else None
            print(f'The fastest instance returned {response.status_code}, choosing another one...')
            url = f"http://{fastest_instance}/{proxy_path}" if not fastest_instance.startswith('http') else f"{fastest_instance}/{proxy_path}"
            continue
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers['Location']
            if not location.startswith('http'):
                location = fastest_instance + location
            url = f"{location.split('//')[0]}//{location.split('//')[1]}/"
            headers['Host'] = location.split('//')[1]
            continue
        if request.method == 'POST' and re.match(r'^https?://co\.wuk\.sh', response.json()['url']):
            # Replacing co.wuk.sh with the current instance, for broken ones
            response_data = response.content.decode('utf-8')
            response_data = response_data.replace('https://co.wuk.sh', (fastest_instance if fastest_instance.startswith('http') else ('https://', fastest_instance)))
        else:
            response_data = response.content
        break
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    headers = [(name, value) for (name, value) in response.raw.headers.items()
               if name.lower() not in excluded_headers]
    headers += [('Access-Control-Allow-Headers', '*')]
    return Response(response_data, response.status_code, headers)

def update_instances():
    while True:
        main()
        print('[cobaltizer] Updated instances! Now using', fastest_instance, 'with ping:', instances_ping.get(fastest_instance, 'N/A'), 'ms') if instances_ping else print('No instances found')
        time.sleep(UPDATE_INSTANCE_TIME * 60)
timer = threading.Thread(target=update_instances).start()
if __name__ == '__main__':
    app.run(port=PORT, debug=False)
