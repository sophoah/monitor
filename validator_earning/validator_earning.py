#!/usr/bin/env python3

import argparse
import json
import requests
from collections import defaultdict
from decimal import Decimal
from os import (
    mkdir,
    path
)
from time import sleep
from statistics import median
from threading import Thread

from AutoNode import common
from jinja2 import (
    Environment,
    FileSystemLoader
)

base = path.dirname(path.realpath(__file__))
data = path.abspath(path.join(base, 'data'))

html_dis = path.join(data, 'earning.html')
raw_data = path.join(data, 'validator_info.json')
net_stat = path.join(data, 'network_stats.json')

rpc_headers = {'Content-Type': 'application/json'}

security_contact = common._validator_config_default['security-contact']
identity = common._validator_config_default['identity']

def rpc_request(method, endpoint, params):
    v_print(f'-- RPC Request: {method}, {params}')
    payload = {"id": "1",
               "jsonrpc": "2.0",
               "method": method,
               "params": params}
    r = requests.request('POST', endpoint, headers = rpc_headers, data = json.dumps(payload), timeout = 5)
    return json.loads(r.content)['result']

# -1 for all, otherwise field is for pagination
def get_all_validators_information(endpoint, page = [-1]):
    return rpc_request('hmy_getAllValidatorInformation', endpoint, page)

def get_super_committees(endpoint):
    return rpc_request('hmy_getSuperCommittees', endpoint, [])

def atto_to_one(atto):
    return Decimal(atto) / Decimal(1e18)

if __name__ == '__main__':
    valid_networks = ['os', 'ps', 'stn']

    parser = argparse.ArgumentParser()
    parser.add_argument('--network_endpoint', choices = valid_networks, help = 'Tag for network endpoint')
    parser.add_argument('--timer', default = 15, help = 'Seconds between iterations')
    parser.add_argument('--verbose', action = 'store_true', help = 'Verbose for debug')

    args = parser.parse_args()

    if args.verbose:
        def v_print(s):
            print(s)
    else:
        def v_print(s):
            return

    if not path.exists(data):
        try:
            mkdir(data)
        except:
            print(f'[WARNING] Data directory already exists: {data}')

    def sleep_timer():
        sleep(args.timer)

    env = Environment(loader = FileSystemLoader(path.join(base, 'app', 'templates')), auto_reload = False)
    template = env.get_template('earning.html.j2')

    endpoint = f'https://api.s0.{args.network_endpoint}.hmny.io'
    network_validators = defaultdict(lambda : defaultdict(lambda: None))
    network_stats = defaultdict(int)

    if path.exists(raw_data):
        with open(raw_data, 'r', encoding = 'utf-8') as f:
            json_string = ''.join([x.strip() for x in f])
        existing_data = json.loads(json_string)
        for k in existing_data.keys():
            for v in existing_data[k].keys():
                network_validators[k][v] = existing_data[k][v]

    while True:
        try:
            sleep_thread = Thread(target = sleep_timer)
            sleep_thread.start()
            validator_information = get_all_validators_information(endpoint)

            elected = []
            not_elected = []

            v_print('-- Processing Validator Information --')
            for info in validator_information:
                validator_address = info['validator']['address']
                val = network_validators[validator_address]
                val['address'] = validator_address
                val['elected'] = info['currently-in-committee']
                val['epos-status'] = info['epos-status']
                val['num-keys'] = len(info['validator']['bls-public-keys'])
                val['stake'] = float(atto_to_one(info['total-delegation']))
                current_earnings = atto_to_one(info['lifetime']['reward-accumulated'])
                if val['lifetime-rewards'] is not None:
                    if val['earned-rewards'] is None:
                        val['earned-rewards'] = []
                    if len(val['earned-rewards']) == 60:
                        val['earned-rewards'] = val['earned-rewards'][1:]
                    val['earned-rewards'].append(float(current_earnings - Decimal(val['lifetime-rewards'])))
                    val['current-earnings'] = sum(val['earned-rewards'])
                else:
                    val['current-earnings'] = float(0)
                if val['earned-rewards'] is not None:
                    val['earning'] = val['current-earnings'] > float(0)
                val['lifetime-rewards'] = float(current_earnings)
                if info['validator']['security-contact'] == 'info@ankr.com':
                    val['tag'] = 'ankr'
                elif info['validator']['security-contact'] == security_contact or info['validator']['identity'] == identity:
                    val['tag'] = 'Autonode'
                else:
                    val['tag'] = ''
                if val['elected']:
                    avail = int(float(info['current-epoch-performance']['current-epoch-signing-percent']['current-epoch-signing-percentage']) * 100)
                    val['availibility'] = avail
                    elected.append(val)
                else:
                    not_elected.append(val)

            elected = sorted(elected, key = lambda x: (x['current-earnings'], x['lifetime-rewards'], x['availibility']), reverse = True)
            not_elected = sorted(not_elected, key = lambda x: (x['stake'], x['epos-status'], x['lifetime-rewards']), reverse = True)

            network_stats['total-validators'] = len(network_validators.keys())
            network_stats['num-elected'] = len(elected)
            network_stats['num-eligible'] = len([x for x in network_validators.keys() if network_validators[x]['epos-status'] == 'eligible to be elected next epoch'])
            network_stats['num-ineligible'] = len([x for x in network_validators.keys() if network_validators[x]['epos-status'] == 'not eligible to be elected next epoch'])

            v_print('-- Writing HTML --')
            with open(path.join(data, 'earning.html'), 'w', encoding = 'utf-8') as f:
                f.write(template.render(elected = elected, not_elected = not_elected, stats = network_stats))

            v_print('-- Writing Validator Information --')
            with open(path.join(data, 'validator_info.json'), 'w', encoding = 'utf-8') as f:
                json.dump(network_validators, f, sort_keys = True, indent = 4)

            v_print('-- Writing Network Stats --')
            with open(path.join(data, 'network_stats.json'), 'w', encoding = 'utf-8') as f:
                json.dump(network_stats, f, sort_keys = True, indent = 4)

            sleep_thread.join()
        except Exception as e:
            print(f'[ERROR]: {e}')
