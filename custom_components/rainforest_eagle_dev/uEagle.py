import json
import time
import requests
from struct import unpack, pack

MDNS_TEMPLATE = r'http://{0}:{1}@eagle-{0}.local'
ADDR_TEMPLATE = r'http://{0}:{1}@{2}'

CMD_TOP_TEMPLATE = r'''<Command>\n
                   <Name>{0!s}</Name>\n
                   <Format>JSON</Format>'''
LOCAL_CMD_TOP_TEMPLATE = r'''<LocalCommand>\n
                         <Name>{0!s}</Name>\n'''


# Options
SAFETY_ON = True

# Enumerations
if SAFETY_ON:
    PROTOCOL_VALS = ('ZigBee',)
    STATUS_VALS   = ('Initializing', 'Network', 'Discovery', 'Joining',
                     'Join: Fail', 'Join: Success', 'Authenticating',
                     'Authenticating: Success', 'Authenticating: Fail',
                     'Connected', 'Disconnected', 'Rejoining')
    YESNO_VALS    = ('Y', 'N')
    PRIORITY_VALS = ('Low', 'Medium', 'High', 'Critical')
    QUEUE_VALS    = ('Active', 'Cancel Pending')
    EVENT_VALS    = ('', 'time', 'message', 'price', 'summation', 'demand',
                     'scheduled_prices', 'profile_data', 'billing_period',
                     'block_period')
    TARGET_VALS   = ('Zigbee', 'Eagle', 'All')


from sys import platform
if platform in ('linux', 'unix'):
    EPOCH_DELTA = 946684800
else:
    EPOCH_DELTA = 0
del platform


class Eagle(object):
    def __init__(self, cloud_id, install_code, address=None):
        self._headers = {'Content-Type': 'application/xml'}

        if address is not None:
            self.addr = ADDR_TEMPLATE.format(cloud_id, install_code, address)
        else:
            self.addr = MDNS_TEMPLATE.format(cloud_id, install_code)

    def make_cmd(self, command, **kws):
        cmd_str = CMD_TOP_TEMPLATE.format(command)

        for k, v in kws.items():
            cmd_str += '<{0}>{1!s}</{0}>\n'.format(k, v)

        cmd_str += '</Command>\n'
        return cmd_str

    def make_local_cmd(self, command, **kws):
        cmd_str = LOCAL_CMD_TOP_TEMPLATE.format(command)

        for k, v in kws.items():
            cmd_str += '<{0}>{1!s}</{0}>\n'.format(k, v)

        cmd_str += '</LocalCommand>\n'
        return cmd_str

    def post_cmd(self, command, **kws):
        api_addr = self.addr + '/cgi-bin/post_manager'
        post_data = self.make_cmd(command, **kws)
        return self.post_cmd_final(api_addr, post_data) 

    def post_local_cmd(self, command, **kws):
        api_addr = self.addr + '/cgi-bin/cgi_manager'
        post_data = self.make_local_cmd(command, **kws)
        return self.post_cmd_final(api_addr, post_data) 

    def post_cmd_final(self, address, post_data):   
        response = requests.post(address,
                                 headers=self._headers,
                                 data=post_data)
        
        if(response.status_code != 200):
            response.raise_for_status()

        response_text = TEMP_RESPONSE_FIX(response.text)

        try:
            data = json.loads(response_text)
        except ValueError as error:
            raise ValueError("Invalid JSON format: %s", error)

        process_data(data)
        return data

    def get_network_info(self):
        return self.post_cmd('get_network_info')

    def list_network(self):
        raise NotImplementedError()  # No JSON support for this command

    def get_network_status(self):
        return self.post_cmd('get_network_status')

    def get_device_list(self):
        return self.post_local_cmd('get_device_list')

    def get_setting_data(self):
        return self.post_local_cmd('get_setting_data')

    def get_instantaneous_demand(self):
        return self.post_cmd('get_instantaneous_demand')

    def get_price(self):
        return self.post_cmd('get_price')

    def get_message(self):
        return self.post_cmd('get_message')

    def confirm_message(self):  # Needs argument: ID
        raise NotImplementedError('uEagle is read-only for now.')

    def get_current_summation(self):
        return self.post_cmd('get_current_summation')

    def get_history_data(self, start_time, end_time=None, frequency=None):
        kw = {'StartTime': hex(int(start_time - EPOCH_DELTA))}

        if end_time is not None:
            kw['EndTime'] = hex(int(end_time - EPOCH_DELTA))

        if frequency is not None:
            if SAFETY_ON:
                if frequency > 0xffff or frequency < 0:
                    raise ValueError('frequency must be between 0 and 65535 seconds')
            kw['Frequency'] = hex(int(frequency))

        return self.post_cmd('get_history_data', **kw)

    def set_schedule(self):  # Needs arguments: Event, Frequency, Enabled
        raise NotImplementedError('uEagle is read-only for now.')

    def get_schedule(self, event=None):
        if event is None:
            event = ''

        if SAFETY_ON and event not in EVENT_VALS:
            raise ValueError('\'{}\' is not a valid event'.format(event))
        return self.post_cmd('get_schedule', Event=event)

    def reboot(self):  # Needs argument: Target
        raise NotImplementedError('uEagle is read-only for now.')

    def get_demand_peaks(self):
        return self.post_cmd('get_demand_peaks')


def process_data(d):
    '''
    Given a response dict from the EAGLE, interpret common data
    types / apply conversions.
    '''
    # Handle nested dictionaries
    for v in d.values():
        if isinstance(v, dict):
            process_data(v)
        elif isinstance(v, list):
            for vi in v:
                process_data(vi)

    # Summation and demand conversion
    if 'Multiplier' in d:
        convert_demand(d)

    if 'Price' in d:
        convert_price(d)

    if 'TimeStamp' in d:
        d['TimeStamp'] = time.localtime(int(d['TimeStamp'], 0) + EPOCH_DELTA)


def convert_demand(d):
    'Parse values and remove extraneous keys from demand responses.'
    factor = max(int(d['Multiplier'], 0), 1) / max(int(d['Divisor'], 0), 1)
    n_dec = int(d['DigitsRight'], 0)

    if 'Demand' in d:
        demand = int(d['Demand'], 0)
        bytes_demand = pack('>I', demand)
        new_int_demand = unpack('>i', bytes_demand)[0]
        d['Demand'] = round(new_int_demand*factor, n_dec)
    else:
        d['SummationDelivered'] = round(int(d['SummationDelivered'], 0)*factor, n_dec)
        d['SummationReceived'] = round(int(d['SummationReceived'], 0)*factor, n_dec)

    del d['Multiplier']
    del d['Divisor']
    del d['DigitsRight']
    del d['DigitsLeft']
    del d['SuppressLeadingZero']


def convert_price(d):
    'Perform inplace hex-to-value conversion for price values.'
    d['Price'] = int(d['Price'], 0) / 10**int(d['TrailingDigits'], 0)
    d['Currency'] = int(d['Currency'], 0)

    del d['TrailingDigits']


def TEMP_RESPONSE_FIX(s):
    '''
    The EAGLE API provides malformed responses for some commands.  This
    function tries to fix them (until the firmware is patched).
    '''
    if s.startswith('\"HistoryData\"') or s.startswith('\"ScheduleList\"'):
        return '{' + s + '}'
    return s

#notes
#More recent API (1.1) supports command list_network
##list_network does not return JSON
##gets info on all network interfaces
#
#When running locally, API Commands to not actually require MAC address

#Since this is python3 compatible, we assumme int / int = float

#the EAGLE's Epoch is 01-01-2000, rather than unix's 1970.
#Each command needs:
# POST with
## headers: auth
## body: xml
#<Command>
# 	<Name>COMMAND</Name>
# 	<Format>JSON</Format>
#   <MAYBE OTHER OPTIONS>
#</Command>


