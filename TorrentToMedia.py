import datetime
import os
import sys

import nzb2media
from nzb2media import logger, main_db
from nzb2media.auto_process import comics, games, movies, music, tv, books
from nzb2media.auto_process.common import ProcessResult
from nzb2media.plugins.plex import plex_update
from nzb2media.user_scripts import external_script
from nzb2media.utils.encoding import char_replace, convert_to_ascii
from nzb2media.utils.links import replace_links


def process_torrent(input_directory, input_name, input_category, input_hash, input_id, client_agent):
    status = 1  # 1 = failed | 0 = success
    root = 0
    found_file = 0

    if client_agent != 'manual' and not nzb2media.DOWNLOAD_INFO:
        logger.debug(f'Adding TORRENT download info for directory {input_directory} to database')

        my_db = main_db.DBConnection()

        input_directory1 = input_directory
        input_name1 = input_name

        try:
            encoded, input_directory1 = char_replace(input_directory)
            encoded, input_name1 = char_replace(input_name)
        except Exception:
            pass

        control_value_dict = {'input_directory': input_directory1}
        new_value_dict = {
            'input_name': input_name1,
            'input_hash': input_hash,
            'input_id': input_id,
            'client_agent': client_agent,
            'status': 0,
            'last_update': datetime.date.today().toordinal(),
        }
        my_db.upsert('downloads', new_value_dict, control_value_dict)

    logger.debug(f'Received Directory: {input_directory} | Name: {input_name} | Category: {input_category}')

    # Confirm the category by parsing directory structure
    input_directory, input_name, input_category, root = nzb2media.category_search(
        input_directory, input_name, input_category,
        root, nzb2media.CATEGORIES,
    )
    if input_category == '':
        input_category = 'UNCAT'

    usercat = input_category

    logger.debug(f'Determined Directory: {input_directory} | Name: {input_name} | Category: {input_category}')

    # auto-detect section
    section = nzb2media.CFG.findsection(input_category).isenabled()
    if section is None: #Check for user_scripts for 'ALL' and 'UNCAT'
        if usercat in nzb2media.CATEGORIES:
            section = nzb2media.CFG.findsection('ALL').isenabled()
            usercat = 'ALL'
        else:
            section = nzb2media.CFG.findsection('UNCAT').isenabled()
            usercat = 'UNCAT'
    if section is None: # We haven't found any categories to process.
        logger.error(f'Category:[{input_category}] is not defined or is not enabled. Please rename it or ensure it is enabled for the appropriate section in your autoProcessMedia.cfg and try again.')
        return [-1, '']

    if len(section) > 1:
        logger.error(f'Category:[{usercat}] is not unique, {section.keys()} are using it. Please rename it or disable all other sections using the same category name in your autoProcessMedia.cfg and try again.')
        return [-1, '']

    if section:
        section_name = section.keys()[0]
        logger.info(f'Auto-detected SECTION:{section_name}')
    else:
        logger.error(f'Unable to locate a section with subsection:{input_category} enabled in your autoProcessMedia.cfg, exiting!')
        return [-1, '']

    section = dict(section[section_name][usercat])  # Type cast to dict() to allow effective usage of .get()

    torrent_no_link = int(section.get('Torrent_NoLink', 0))
    keep_archive = int(section.get('keep_archive', 0))
    extract = int(section.get('extract', 0))
    extensions = section.get('user_script_mediaExtensions', '')
    unique_path = int(section.get('unique_path', 1))

    if client_agent != 'manual':
        nzb2media.pause_torrent(client_agent, input_hash, input_id, input_name)

    # In case input is not directory, make sure to create one.
    # This way Processing is isolated.
    if not os.path.isdir(os.path.join(input_directory, input_name)):
        basename = os.path.basename(input_directory)
        basename = nzb2media.sanitize_name(input_name) \
            if input_name == basename else os.path.splitext(nzb2media.sanitize_name(input_name))[0]
        output_destination = os.path.join(nzb2media.OUTPUT_DIRECTORY, input_category, basename)
    elif unique_path:
        output_destination = os.path.normpath(
            nzb2media.os.path.join(nzb2media.OUTPUT_DIRECTORY, input_category, nzb2media.sanitize_name(input_name).replace(' ', '.')),
        )
    else:
        output_destination = os.path.normpath(
            nzb2media.os.path.join(nzb2media.OUTPUT_DIRECTORY, input_category),
        )

    if output_destination in input_directory:
        output_destination = input_directory

    logger.info(f'Output directory set to: {output_destination}')

    if nzb2media.SAFE_MODE and output_destination == nzb2media.TORRENT_DEFAULT_DIRECTORY:
        logger.error(f'The output directory:[{input_directory}] is the Download Directory. Edit outputDirectory in autoProcessMedia.cfg. Exiting')
        return [-1, '']

    logger.debug(f'Scanning files in directory: {input_directory}')

    if section_name in ['HeadPhones', 'Lidarr']:
        nzb2media.NOFLATTEN.extend(
            input_category,
        )  # Make sure we preserve folder structure for HeadPhones.

    now = datetime.datetime.now()

    if extract == 1:
        input_files = nzb2media.list_media_files(input_directory, archives=False, other=True, otherext=extensions)
    else:
        input_files = nzb2media.list_media_files(input_directory, other=True, otherext=extensions)
    if len(input_files) == 0 and os.path.isfile(input_directory):
        input_files = [input_directory]
        logger.debug(f'Found 1 file to process: {input_directory}')
    else:
        logger.debug(f'Found {len(input_files)} files in {input_directory}')
    for inputFile in input_files:
        file_path = os.path.dirname(inputFile)
        file_name, file_ext = os.path.splitext(os.path.basename(inputFile))
        full_file_name = os.path.basename(inputFile)

        target_file = nzb2media.os.path.join(output_destination, full_file_name)
        if input_category in nzb2media.NOFLATTEN:
            if not os.path.basename(file_path) in output_destination:
                target_file = nzb2media.os.path.join(
                    nzb2media.os.path.join(output_destination, os.path.basename(file_path)), full_file_name,
                )
                logger.debug(f'Setting outputDestination to {os.path.dirname(target_file)} to preserve folder structure')
        if root == 1:
            if not found_file:
                logger.debug(f'Looking for {input_name} in: {inputFile}')
            if any([
                nzb2media.sanitize_name(input_name) in nzb2media.sanitize_name(inputFile),
                nzb2media.sanitize_name(file_name) in nzb2media.sanitize_name(input_name),
            ]):
                found_file = True
                logger.debug(f'Found file {full_file_name} that matches Torrent Name {input_name}')
            else:
                continue

        if root == 2:
            mtime_lapse = now - datetime.datetime.fromtimestamp(os.path.getmtime(inputFile))
            ctime_lapse = now - datetime.datetime.fromtimestamp(os.path.getctime(inputFile))

            if not found_file:
                logger.debug('Looking for files with modified/created dates less than 5 minutes old.')
            if (mtime_lapse < datetime.timedelta(minutes=5)) or (ctime_lapse < datetime.timedelta(minutes=5)):
                found_file = True
                logger.debug(f'Found file {full_file_name} with date modified/created less than 5 minutes ago.')
            else:
                continue  # This file has not been recently moved or created, skip it

        if torrent_no_link == 0:
            try:
                nzb2media.copy_link(inputFile, target_file, nzb2media.USE_LINK)
                nzb2media.remove_read_only(target_file)
            except Exception:
                logger.error(f'Failed to link: {inputFile} to {target_file}')

    input_name, output_destination = convert_to_ascii(input_name, output_destination)

    if extract == 1:
        logger.debug(f'Checking for archives to extract in directory: {input_directory}')
        nzb2media.extract_files(input_directory, output_destination, keep_archive)

    if input_category not in nzb2media.NOFLATTEN:
        # don't flatten hp in case multi cd albums, and we need to copy this back later.
        nzb2media.flatten(output_destination)

    # Now check if video files exist in destination:
    if section_name in ['SickBeard', 'SiCKRAGE', 'NzbDrone', 'Sonarr', 'CouchPotato', 'Radarr', 'Watcher3']:
        num_videos = len(
            nzb2media.list_media_files(output_destination, media=True, audio=False, meta=False, archives=False),
        )
        if num_videos > 0:
            logger.info(f'Found {num_videos} media files in {output_destination}')
            status = 0
        elif extract != 1:
            logger.info(f'Found no media files in {output_destination}. Sending to {section_name} to process')
            status = 0
        else:
            logger.warning(f'Found no media files in {output_destination}')

    # Only these sections can handling failed downloads
    # so make sure everything else gets through without the check for failed
    if section_name not in ['CouchPotato', 'Radarr', 'SickBeard', 'SiCKRAGE', 'NzbDrone', 'Sonarr', 'Watcher3']:
        status = 0

    logger.info(f'Calling {section_name}:{usercat} to post-process:{input_name}')

    if nzb2media.TORRENT_CHMOD_DIRECTORY:
        nzb2media.rchmod(output_destination, nzb2media.TORRENT_CHMOD_DIRECTORY)

    if section_name == 'UserScript':
        result = external_script(output_destination, input_name, input_category, section)
    else:
        process_map = {
            'CouchPotato': movies.process,
            'Radarr': movies.process,
            'Watcher3': movies.process,
            'SickBeard': tv.process,
            'SiCKRAGE': tv.process,
            'NzbDrone': tv.process,
            'Sonarr': tv.process,
            'LazyLibrarian': books.process,
            'HeadPhones': music.process,
            'Lidarr': music.process,
            'Mylar': comics.process,
            'Gamez': games.process,
        }
        if input_hash and section_name in ['SickBeard', 'SiCKRAGE', 'NzbDrone', 'Sonarr']:
            input_hash = input_hash.upper()
        processor = process_map[section_name]
        result = processor(
            section=section_name,
            dir_name=output_destination,
            input_name=input_name,
            status=status,
            client_agent=client_agent,
            download_id=input_hash,
            input_category=input_category,
        )

    plex_update(input_category)

    if result.status_code != 0:
        if not nzb2media.TORRENT_RESUME_ON_FAILURE:
            logger.error(
                'A problem was reported in the autoProcess* script. '
                'Torrent won\'t resume seeding (settings)',
            )
        elif client_agent != 'manual':
            logger.error(
                'A problem was reported in the autoProcess* script. '
                'If torrent was paused we will resume seeding',
            )
            nzb2media.resume_torrent(client_agent, input_hash, input_id, input_name)

    else:
        if client_agent != 'manual':
            # update download status in our DB
            nzb2media.update_download_info_status(input_name, 1)

            # remove torrent
            if nzb2media.USE_LINK == 'move-sym' and not nzb2media.DELETE_ORIGINAL == 1:
                logger.debug(f'Checking for sym-links to re-direct in: {input_directory}')
                for dirpath, _, files in os.walk(input_directory):
                    for file in files:
                        logger.debug(f'Checking symlink: {os.path.join(dirpath, file)}')
                        replace_links(os.path.join(dirpath, file))
            nzb2media.remove_torrent(client_agent, input_hash, input_id, input_name)

        if section_name != 'UserScript':
            # for user script, we assume this is cleaned by the script or option USER_SCRIPT_CLEAN
            # cleanup our processing folders of any misc unwanted files and empty directories
            nzb2media.clean_dir(output_destination, section_name, input_category)

    return result


def main(args):
    # Initialize the config
    nzb2media.initialize()

    # clientAgent for Torrents
    client_agent = nzb2media.TORRENT_CLIENT_AGENT

    logger.info('#########################################################')
    logger.info(f'## ..::[{os.path.basename(__file__)}]::.. ##')
    logger.info('#########################################################')

    # debug command line options
    logger.debug(f'Options passed into TorrentToMedia: {args}')

    # Post-Processing Result
    result = ProcessResult(
        message='',
        status_code=0,
    )

    try:
        input_directory, input_name, input_category, input_hash, input_id = nzb2media.parse_args(client_agent, args)
    except Exception:
        logger.error('There was a problem loading variables')
        return -1

    if input_directory and input_name and input_hash and input_id:
        result = process_torrent(input_directory, input_name, input_category, input_hash, input_id, client_agent)
    elif nzb2media.TORRENT_NO_MANUAL:
        logger.warning('Invalid number of arguments received from client, and no_manual set')
    else:
        # Perform Manual Post-Processing
        logger.warning('Invalid number of arguments received from client, Switching to manual run mode ...')

        for section, subsections in nzb2media.SECTIONS.items():
            for subsection in subsections:
                if not nzb2media.CFG[section][subsection].isenabled():
                    continue
                for dir_name in nzb2media.get_dirs(section, subsection, link='hard'):
                    logger.info(f'Starting manual run for {section}:{subsection} - Folder:{dir_name}')

                    logger.info(f'Checking database for download info for {os.path.basename(dir_name)} ...')
                    nzb2media.DOWNLOAD_INFO = nzb2media.get_download_info(os.path.basename(dir_name), 0)
                    if nzb2media.DOWNLOAD_INFO:
                        client_agent = nzb2media.DOWNLOAD_INFO[0]['client_agent'] or 'manual'
                        input_hash = nzb2media.DOWNLOAD_INFO[0]['input_hash'] or ''
                        input_id = nzb2media.DOWNLOAD_INFO[0]['input_id'] or ''
                        logger.info(f'Found download info for {os.path.basename(dir_name)}, setting variables now ...')
                    else:
                        logger.info(f'Unable to locate download info for {os.path.basename(dir_name)}, continuing to try and process this release ...')
                        client_agent = 'manual'
                        input_hash = ''
                        input_id = ''

                    if client_agent.lower() not in nzb2media.TORRENT_CLIENTS:
                        continue

                    input_name = os.path.basename(dir_name)

                    results = process_torrent(
                        dir_name, input_name, subsection, input_hash or None, input_id or None,
                        client_agent,
                    )
                    if results.status_code != 0:
                        logger.error(f'A problem was reported when trying to perform a manual run for {section}:{subsection}.')
                        result = results

    if result.status_code == 0:
        logger.info(f'The {args[0]} script completed successfully.')
    else:
        logger.error(f'A problem was reported in the {args[0]} script.')
    del nzb2media.MYAPP
    return result.status_code


if __name__ == '__main__':
    exit(main(sys.argv))
