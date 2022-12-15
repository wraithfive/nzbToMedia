from __future__ import annotations

import os

import requests

import nzb2media
from nzb2media import logger


def get_nzoid(input_name):
    nzoid = None
    slots = []
    logger.debug('Searching for nzoid from SAbnzbd ...')
    if 'http' in nzb2media.SABNZBD_HOST:
        base_url = f'{nzb2media.SABNZBD_HOST}:{nzb2media.SABNZBD_PORT}/api'
    else:
        base_url = f'http://{nzb2media.SABNZBD_HOST}:{nzb2media.SABNZBD_PORT}/api'
    url = base_url
    params = {
        'apikey': nzb2media.SABNZBD_APIKEY,
        'mode': 'queue',
        'output': 'json',
    }
    try:
        r = requests.get(url, params=params, verify=False, timeout=(30, 120))
    except requests.ConnectionError:
        logger.error('Unable to open URL')
        return nzoid  # failure
    try:
        result = r.json()
        clean_name = os.path.splitext(os.path.split(input_name)[1])[0]
        slots.extend(
            [
                (slot['nzo_id'], slot['filename'])
                for slot in result['queue']['slots']
            ],
        )
    except Exception:
        logger.warning('Data from SABnzbd queue could not be parsed')
    params['mode'] = 'history'
    try:
        r = requests.get(url, params=params, verify=False, timeout=(30, 120))
    except requests.ConnectionError:
        logger.error('Unable to open URL')
        return nzoid  # failure
    try:
        result = r.json()
        clean_name = os.path.splitext(os.path.split(input_name)[1])[0]
        slots.extend(
            [
                (slot['nzo_id'], slot['name'])
                for slot in result['history']['slots']
            ],
        )
    except Exception:
        logger.warning('Data from SABnzbd history could not be parsed')
    try:
        for nzo_id, name in slots:
            if name in [input_name, clean_name]:
                nzoid = nzo_id
                logger.debug(f'Found nzoid: {nzoid}')
                break
    except Exception:
        logger.warning('Data from SABnzbd could not be parsed')
    return nzoid


def report_nzb(failure_link, client_agent):
    # Contact indexer site
    logger.info('Sending failure notification to indexer site')
    if client_agent == 'nzbget':
        headers = {'User-Agent': 'NZBGet / nzbToMedia.py'}
    elif client_agent == 'sabnzbd':
        headers = {'User-Agent': 'SABnzbd / nzbToMedia.py'}
    else:
        return
    try:
        requests.post(failure_link, headers=headers, timeout=(30, 300))
    except Exception as e:
        logger.error(f'Unable to open URL {failure_link} due to {e}')
    return