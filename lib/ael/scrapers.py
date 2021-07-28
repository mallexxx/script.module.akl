# -*- coding: utf-8 -*-

# Advanced Emulator Launcher scraping engine.
#
# --- Information about scraping ---
# https://github.com/muldjord/skyscraper
# https://github.com/muldjord/skyscraper/blob/master/docs/SCRAPINGMODULES.md

# Copyright (c) 2016-2019 Wintermute0110 <wintermute0110@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.


# --- Python standard library ---
from __future__ import unicode_literals
from __future__ import division

import logging
import collections
import abc
import datetime, time
import os
import re
import json

from ael.utils import kodi, io, net, text
from ael import constants, platforms

logger = logging.getLogger(__name__)

# --- Scraper use cases ---------------------------------------------------------------------------
# THIS DOCUMENTATION IS OBSOLETE, IT MUST BE UPDATED TO INCLUDE THE SCRAPER DISK CACHE.
#
# The ScraperFactory class is resposible to create a ScraperStrategy object according to the
# addon settings and to keep a cached dictionary of Scraper objects.
#
# The actual scraping is done by the ScraperStrategy object, which has the logic to download
# images, rename them, etc., and to interact with the scraped object (ROM, Std Launchers).
#
# The Scraper objects only know of to pull information from websites or offline XML databases.
# Scraper objects do not need to reference Launcher or ROM objects. Pass to them the required
# properties like platform. Launcher and ROM objects are know by the ScraperStrategy but not
# by the Scraper objects.
#
# --- NOTES ---
# 1) There is one and only one global ScraperFactory object named g_scraper_factory.
#
# 2) g_scraper_factory keeps a list of instantiated scraper objects. Scrapers are identified
#    with a numerical list index. This is required to identify a concrete scraper object
#    from the addon settings.
#
# 3) g_scraper_factory must be able to report each scraper capabilities.
#
# 4) The actual object metadata/asset scraping is done by an scrap_strategy object instance.
#
# 5) progress_dialog_obj object instance is passed to the scrap_strategy instance.
#    In the ROM scanner the progress dialog is created in the scanner instance and 
#    changed by the scanner/scraper objects.
#
# --- Use case A: ROM scanner ---------------------------------------------------------------------
# The ROM scanner case also applies when the user selects "Rescrape ROM assets" in the Launcher
# context menu.
#
# --- Algorithm ---
# 1) Create a ScraperFactory global object g_scraper_factory.
# 1.1) For each scraper class one and only one object is instantiated and initialised.
#      This per-scraper unique object simplifies the coding of the scraper cache.
#      The unique scraper objects are stored inside the global g_scraper_factory and can
#      be reused.
#
# 2) Create a ScraperStrategy object with the g_scraper_factory object.
# 2.1) g_scraper_factory checks for unset artwork directories. Disable unconfigured assets.
# 2.2) Check for duplicate artwork directories. Disable assets for duplicated directories.
# 2.3) Read the addon settings and create the metadata scraper to process ROMs.
# 2.4) For each asset type not disabled create the asset scraper.
# 2.5) Finally, create and return the ScraperStrategy object.
#
# 3) For each ROM object scrape the metadata and assets with the ScraperStrategy object.
#
# --- Code example ---
# scrap_strategy.process_ROM() scrapes all enabled assets in sequence using all the
# configured scrapers (primary, secondary).
#
# g_scraper_factory = ScraperFactory(g_PATHS, g_settings)
# scrap_strategy = g_scraper_factory.create_scanner(launcher_obj, progress_dialog_obj)
# scrap_strategy.process_ROM(rom_obj, None))
#
# --- Use case B: ROM context menu ---------------------------------------------------------------
# In the ROM context menu the scraper object may be called multiple times by the recursive
# context menu.
#
# Scrapers should report the assets they support to build the dynamic context menu.
#
# The scraping mode when using the context menu is always manual.
#
# --- Use case C: Standalone Launcher context menu -----------------------------------------------
# In the Standalone Launcher context menu the situation is similar to the ROM context menu.
# The difference is that rom_obj is a Launcher object instance instead of a ROM object.
# -----------------------------------------------------------------------------------------------
class ScraperSettings(object): 
    
    def __init__(self):
        self.metadata_scraper_ID = constants.SCRAPER_NULL_ID
        self.assets_scraper_ID   = constants.SCRAPER_NULL_ID
        
        self.scrape_metadata_policy = constants.SCRAPE_POLICY_TITLE_ONLY
        self.scrape_assets_policy   = constants.SCRAPE_POLICY_LOCAL_ONLY
        
        self.search_term_mode       = constants.SCRAPE_AUTOMATIC
        self.game_selection_mode    = constants.SCRAPE_AUTOMATIC
        self.asset_selection_mode   = constants.SCRAPE_AUTOMATIC
        
        self.asset_IDs_to_scrape = constants.ROM_ASSET_ID_LIST
        self.overwrite_existing = False
        self.show_info_verbose = False
    
    def build_menu(self):
        options = collections.OrderedDict()        
        options['SC_METADATA_POLICY']      = 'Metadata scan policy: "{}"'.format(kodi.translate(self.scrape_metadata_policy))
        options['SC_ASSET_POLICY']         = 'Asset scan policy: "{}"'.format(kodi.translate(self.scrape_assets_policy))
        options['SC_GAME_SELECTION_MODE']  = 'Game selection mode: "{}"'.format(kodi.translate(self.game_selection_mode))
        options['SC_ASSET_SELECTION_MODE'] = 'Asset selection mode: "{}"'.format(kodi.translate(self.asset_selection_mode))
        options['SC_OVERWRITE_MODE']       = 'Overwrite existing files: "{}"'.format('Yes' if self.overwrite_existing else 'No')
        options['SC_METADATA_SCRAPER']     = 'Metadata scraper: "{}"'.format(kodi.translate(self.metadata_scraper_ID))
        options['SC_ASSET_SCRAPER']        = 'Asset scraper: "{}"'.format(kodi.translate(self.assets_scraper_ID))        
        return options
    
    def get_data_dic(self) -> dict:
        return {
            'scrape_metadata_policy': self.scrape_metadata_policy,
            'scrape_assets_policy': self.scrape_assets_policy,
            'game_selection_mode': self.game_selection_mode,
            'asset_selection_mode': self.asset_selection_mode
        }
            
    @staticmethod
    def from_settings_dict(settings:dict):
        
        scraper_settings = ScraperSettings()   
        #scraper_settings.metadata_scraper_ID    = settings['scraper_metadata']
        #scraper_settings.assets_scraper_ID      = settings['scraper_asset']
            
        scraper_settings.scrape_metadata_policy = settings['scan_metadata_policy']
        scraper_settings.scrape_assets_policy   = settings['scan_asset_policy']
        scraper_settings.game_selection_mode    = settings['game_selection_mode']
        scraper_settings.asset_selection_mode   = settings['asset_selection_mode']    
        
        return scraper_settings
    
# This class is used to filter No-Intro BIOS ROMs and MAME BIOS, Devices and Mecanichal machines.
# No-Intro BIOSes are easy to filter, filename starts with '[BIOS]'
# MAME is more complicated. The Offline Scraper includes 3 JSON filenames
#   MAME_BIOSes.json
#   MAME_Devices.json
#   MAME_Mechanical.json
# used to filter MAME machines.
# This class is (will be) used in the ROM Scanner.
class FilterROM(object):
    def __init__(self, PATHS, settings, platform):
        logger.debug('FilterROM.__init__() BEGIN...')
        self.PATHS = PATHS
        self.settings = settings
        self.platform = platform
        self.addon_dir = self.settings['scraper_aeloffline_addon_code_dir']

        # If platform is MAME load the BIOS, Devices and Mechanical databases.
        if self.platform == platforms.PLATFORM_MAME_LONG:
            BIOS_path       = os.path.join(self.addon_dir, 'data-AOS', 'MAME_BIOSes.json')
            Devices_path    = os.path.join(self.addon_dir, 'data-AOS', 'MAME_Devices.json')
            Mechanical_path = os.path.join(self.addon_dir, 'data-AOS', 'MAME_Mechanical.json')
            BIOS_list       = self._load_JSON(BIOS_path)
            Devices_list    = self._load_JSON(Devices_path)
            Mechanical_list = self._load_JSON(Mechanical_path)
            # Convert lists to sets to execute efficiently 'x in y' operation.
            self.BIOS_set = {i for i in BIOS_list}
            self.Devices_set = {i for i in Devices_list}
            self.Mechanical_set = {i for i in Mechanical_list}

    def _load_JSON(self, filename):
        logger.debug('FilterROM::_load_JSON() Loading "{}"'.format(filename))
        with open(filename) as file:
            data = json.load(file)

        return data

    # Returns True if ROM is filtered, False otherwise.
    def ROM_is_filtered(self, basename):
        logger.debug('FilterROM::ROM_is_filtered() Testing "{}"'.format(basename))
        if not self.settings['scan_ignore_bios']:
            logger.debug('FilterROM::ROM_is_filtered() Filters disabled. Return False.')
            return False

        if self.platform == platforms.PLATFORM_MAME_LONG:
            if basename in self.BIOS_set:
                logger.debug('FilterROM::ROM_is_filtered() Filtered MAME BIOS "{}"'.format(basename))
                return True
            if basename in self.Devices_set:
                logger.debug('FilterROM::ROM_is_filtered() Filtered MAME Device "{}"'.format(basename))
                return True
            if basename in self.Mechanical_set:
                logger.debug('FilterROM::ROM_is_filtered() Filtered MAME Mechanical "{}"'.format(basename))
                return True
        else:
            # If it is not MAME it is No-Intro
            # Name of bios is: '[BIOS] Rom name example (Rev A).zip'
            BIOS_m = re.findall('\[BIOS\]', basename)
            if BIOS_m:
                logger.debug('FilterROM::ROM_is_filtered() Filtered No-Intro BIOS "{}"'.format(basename))
                return True

        return False
         
#
# Main scraping logic.
#
class ScrapeStrategy(object):
    # --- Class variables ------------------------------------------------------------------------
    # --- Metadata actions ---
    ACTION_META_NONE       = 0
    ACTION_META_TITLE_ONLY = 100
    ACTION_META_NFO_FILE   = 200
    ACTION_META_SCRAPER    = 300

    # --- Asset actions ---
    ACTION_ASSET_NONE        = 0
    ACTION_ASSET_LOCAL_ASSET = 100
    ACTION_ASSET_SCRAPER     = 200

    SCRAPE_ROM      = 'ROM'
    SCRAPE_LAUNCHER = 'Launcher'

    # --- Constructor ----------------------------------------------------------------------------
    # @param PATHS: PATH object.
    # @param settings: [dict] Addon settings.
    def __init__(self, PATHS, settings, scraper_settings: ScraperSettings):
        logger.debug('ScrapeStrategy.__init__() Initializing ScrapeStrategy...')
        self.PATHS = PATHS
        self.settings = settings
        self.scraper_settings = scraper_settings
        
        # default set to None so that reference exists
        self.meta_scraper_obj   = None
        self.asset_scraper_obj  = None

        # Boolean options used by the scanner.
        self.scan_ignore_scrap_title = self.settings['scan_ignore_scrap_title']
        self.scan_clean_tags         = self.settings['scan_clean_tags']
        self.scan_update_NFO_files   = self.settings['scan_update_NFO_files']
        
        self.pdialogger.debugose = scraper_settings.show_info_verbose        

    # Call this function before the ROM Scanning starts.
    def scanner_set_progress_dialog(self, pdialog, pdialogger_debug):
        logger.debug('ScrapeStrategy.scanner_set_progress_dialog() Setting progress dialog...')
        self.pdialog = pdialog
        self.pdialog_debug = pdialogger_debug
        
        # DEBUG code, never use in a release.
        # logger.debug('ScrapeStrategy.begin_ROM_scanner() DEBUG dumping of scraper data ON.')
        # self.meta_scraper_obj.set_debug_file_dump(True, '/home/kodi/')
        # self.asset_scraper_obj.set_debug_file_dump(True, '/home/kodi/')

    # Check if scraper is ready for operation (missing API keys, etc.). If not disable scraper.
    # Display error reported in status_dic as Kodi dialogs.
    def scanner_check_before_scraping(self):
        status_dic = kodi.new_status_dic('No error')
        
        if self.scraper_settings.scrape_metadata_policy is not constants.SCRAPE_ACTION_NONE:
            self.meta_scraper_obj.check_before_scraping(status_dic)
            if not status_dic['status']: kodi.dialog_OK(status_dic['msg'])

        # Only check asset scraper if it's different from the metadata scraper.
        if self.scraper_settings.scrape_assets_policy is not constants.SCRAPE_ACTION_NONE:
            if not self.meta_and_asset_scraper_same:
                status_dic = kodi.new_status_dic('No error')
                self.asset_scraper_obj.check_before_scraping(status_dic)
                if not status_dic['status']: kodi.dialog_OK(status_dic['msg'])

    def scanner_check_launcher_unset_asset_dirs(self):
        logger.debug('ScrapeStrategy::scanner_check_launcher_unset_asset_dirs() BEGIN ...')
        
        rom_asset_states = self.launcher.get_ROM_assets_enabled_statusses(self.scraper_settings.asset_IDs_to_scrape)
        self.enabled_asset_list = []
        unconfigured_name_list = []
        for rom_asset, enabled_state in rom_asset_states.items():
            if not enabled_state:
                logger.debug('Directory not set. Asset "{}" will be disabled'.format(rom_asset))
                unconfigured_name_list.append(rom_asset.name)
            else:
                self.enabled_asset_list.append(rom_asset)
                
        if unconfigured_name_list:
            unconfigured_asset_srt = ', '.join(unconfigured_name_list)
            msg = 'Assets directories not set: {0}. '.format(unconfigured_asset_srt)
            msg = msg + 'Asset scanner will be disabled for this/those.'                                
            logger.debug(msg)
            kodi.dialog_OK(msg)
 
    def scanner_process_launcher(self, launcher):        
        roms = self.launcher.get_roms()
        num_items = len(roms)
        num_items_checked = 0
        self.pdialog.startProgress('Scraping ROMs in launcher', num_items)
        logger.debug('============================== Scraping ROMs ==============================')
        
        for rom in sorted(roms):
            self.pdialog.updateProgress(num_items_checked)
            num_items_checked = num_items_checked + 1
            ROM_file = rom.get_file()
            file_text = 'ROM {}'.format(ROM_file.getBase())
            
            self.pdialog.updateMessages(file_text, 'Scraping {}...'.format(ROM_file.getBaseNoExt()))
            try:
                self.scanner_process_ROM(rom, ROM_file)
            except Exception as ex:
                logger.error('(Exception) Object type "{}"'.format(type(ex)))
                logger.error('(Exception) Message "{}"'.format(str(ex)))
                logger.warning('Could not scrape "{}"'.format(ROM_file.getBaseNoExt()))
                kodi.notify_warn('Could not scrape "{}"'.format(rom.get_name()))
            
            # ~~~ Check if user pressed the cancel button ~~~
            if self.pdialog.isCanceled():
                self.pdialog.endProgress()
                kodi.dialog_OK('Stopping ROM scraping.')
                logger.info('User pressed Cancel button when scraping ROMs. ROM scraping stopped.')
                return None
            
        self.pdialog.endProgress()
        return roms
    
    def scanner_process_ROM(self, ROM, ROM_checksums):
        logger.debug('ScrapeStrategy.scanner_process_ROM() Determining metadata and asset actions...')
                
        if self.scraper_settings.scrape_metadata_policy is not constants.SCRAPE_ACTION_NONE:
            self._scanner_process_ROM_metadata_begin(ROM)
        
        if self.scraper_settings.scrape_assets_policy is not constants.SCRAPE_ACTION_NONE:
            self._scanner_process_ROM_assets_begin(ROM)

        # --- If metadata or any asset is scraped then select the game among the candidates ---
        # Note that the metadata and asset scrapers may be different. If so, candidates
        # must be selected for both scrapers.
        #
        # If asset scraper is needed and metadata and asset scrapers are the same.
        # Do nothing because both scraper objects are really the same object and candidate has been
        # set internally in the scraper object. Unless candidate selection was skipped for metadata.
        status_dic = kodi.new_status_dic('No error')

        ROM_path = ROM.get_file()
        search_term = text.format_ROM_name_for_scraping(ROM_path.getBaseNoExt())
        if self.scraper_settings.search_term_mode == constants.SCRAPE_MANUAL:            
            search_term = kodi.dialog_GetText('Search term', search_term)
            
        logger.debug('ScrapeStrategy.scanner_process_ROM() Getting candidates for game')
        meta_candidate_set = False
        if self.scraper_settings.scrape_metadata_policy != constants.SCRAPE_ACTION_NONE:
            if self.metadata_action == ScrapeStrategy.ACTION_META_SCRAPER:
                self._scanner_get_candidate(ROM, ROM_checksums, search_term, self.meta_scraper_obj, status_dic)
            meta_candidate_set = True
        
        asset_candidate_set = False
        if self.scraper_settings.scrape_assets_policy != constants.SCRAPE_ACTION_NONE:
            if not self.meta_and_asset_scraper_same and not meta_candidate_set:
                self._scanner_get_candidate(ROM, ROM_checksums, search_term, self.asset_scraper_obj, status_dic)
                asset_candidate_set = True
            else: logger.debug('Asset candidate game same as metadata candidate. Doing nothing.')
                
        if not meta_candidate_set: logger.debug('Metadata candidate game is not set')
        if not asset_candidate_set: logger.debug('Asset candidate game is not set')
            
        if self.scraper_settings.scrape_metadata_policy != constants.SCRAPE_ACTION_NONE:
            self._scanner_process_ROM_metadata(ROM)
        
        if self.scraper_settings.scrape_assets_policy != constants.SCRAPE_ACTION_NONE:
            self._scanner_process_ROM_assets(ROM)
                 
    # Called by the ROM scanner. Fills in the ROM metadata.
    #
    # @param ROM: [Rom] ROM object.
    def _scanner_process_ROM_metadata(self, ROM):
        logger.debug('ScrapeStrategy::scanner_process_ROM_metadata() Processing metadata action...')
        if self.metadata_action == ScrapeStrategy.ACTION_META_NONE: return
                
        if self.metadata_action == ScrapeStrategy.ACTION_META_TITLE_ONLY:
            if self.pdialogger.debugose:
                self.pdialog.updateMessage2('Formatting ROM name...')
            ROM_path = ROM.get_file()
            ROM.set_name(text_format_ROM_title(ROM_path.getBaseNoExt(), self.scan_clean_tags))

        elif self.metadata_action == ScrapeStrategy.ACTION_META_NFO_FILE:
            ROM_path = ROM.get_file()
            NFO_file = FileName(ROM_path.getPathNoExt() + '.nfo')
        
            if self.pdialogger.debugose:
                self.pdialog.updateMessage2('Loading NFO file {0}'.format(self.NFO_file.getPath()))
            ROM.update_with_nfo_file(NFO_file, self.pdialogger.debugose)

        elif self.metadata_action == ScrapeStrategy.ACTION_META_SCRAPER:
            self._scanner_scrap_ROM_metadata(ROM)
        else:
            raise ValueError('Invalid metadata_action value {0}'.format(metadata_action))

    # Called by the ROM scanner. Fills in the ROM assets.
    #
    # @param ROM: [ROM] ROM data object. Mutable and edited by assignment.
    def _scanner_process_ROM_assets(self, ROM):
        logger.debug('ScrapeStrategy.scanner_process_ROM_assets() Processing asset actions...')
        
        if all(asset_action == ScrapeStrategy.ACTION_ASSET_NONE for asset_action in self.asset_action_list.values()):
            return
        
        # --- Process asset by asset actions ---
        # --- Asset scraping ---
        for AInfo in self.enabled_asset_list:
            if self.asset_action_list[AInfo.id] == ScrapeStrategy.ACTION_ASSET_NONE:
                logger.debug('Skipping asset scraping for {}'.format(AInfo.name))
                continue    
            elif not self.scraper_settings.overwrite_existing and ROM.has_asset(AInfo):
                logger.debug('Asset {} already exists. Skipping (no overwrite)'.format(AInfo.name))
                continue
            elif self.asset_action_list[AInfo.id] == ScrapeStrategy.ACTION_ASSET_LOCAL_ASSET:
                logger.debug('Using local asset for {}'.format(AInfo.name))
                ROM.set_asset(AInfo, self.local_asset_list[AInfo.id])
            elif self.asset_action_list[AInfo.id] == ScrapeStrategy.ACTION_ASSET_SCRAPER:
                asset_path = self._scanner_scrap_ROM_asset(AInfo, self.local_asset_list[AInfo.id], ROM)
                if asset_path is None:
                    logger.debug('No asset scraped. Skipping {}'.format(AInfo.name))
                    continue      
                if AInfo.id == constants.ASSET_TRAILER_ID:
                    ROM.set_trailer(asset_path)
                else:                       
                    ROM.set_asset(AInfo, asset_path)
            else:
                raise ValueError('Asset {} index {} ID {} unknown action {}'.format(
                    AInfo.name, i, AInfo.id, self.asset_action_list[AInfo.id]))

        romdata = ROM.get_data_dic()
        # --- Print some debug info ---
        logger.debug('Set Title     file "{}"'.format(romdata['s_title']))
        logger.debug('Set Snap      file "{}"'.format(romdata['s_snap']))
        logger.debug('Set Boxfront  file "{}"'.format(romdata['s_boxfront']))
        logger.debug('Set Boxback   file "{}"'.format(romdata['s_boxback']))
        logger.debug('Set Cartridge file "{}"'.format(romdata['s_cartridge']))
        logger.debug('Set Fanart    file "{}"'.format(romdata['s_fanart']))
        logger.debug('Set Banner    file "{}"'.format(romdata['s_banner']))
        logger.debug('Set Clearlogo file "{}"'.format(romdata['s_clearlogo']))
        logger.debug('Set Flyer     file "{}"'.format(romdata['s_flyer']))
        logger.debug('Set Map       file "{}"'.format(romdata['s_map']))
        logger.debug('Set Manual    file "{}"'.format(romdata['s_manual']))
        logger.debug('Set Trailer   file "{}"'.format(romdata['s_trailer']))

        return ROM

    # Determine the actions to be carried out by process_ROM_metadata()
    def _scanner_process_ROM_metadata_begin(self, ROM):
        logger.debug('ScrapeStrategy._scanner_process_ROM_metadata_begin() Determining metadata actions...')
  
        if self.meta_scraper_obj is None:
            logger.debug('ScrapeStrategy::_scanner_process_ROM_metadata_begin() No metadata scraper set, disabling metadata scraping.')
            self.metadata_action = ScrapeStrategy.ACTION_META_NONE
            return
        
        # --- Determine metadata action ----------------------------------------------------------
        # --- Test if NFO file exists ---        
        ROM_path = ROM.get_file()
        self.NFO_file = io.FileName(ROM_path.getPathNoExt() + '.nfo')
        NFO_file_found = True if self.NFO_file.exists() else False
        if NFO_file_found:
            logger.debug('NFO file found "{0}"'.format(self.NFO_file.getPath()))
        else:
            logger.debug('NFO file NOT found "{0}"'.format(self.NFO_file.getPath()))

        # Action depends configured metadata policy and wheter the NFO files was found or not.
        if self.scraper_settings.scrape_metadata_policy == constants.SCRAPE_POLICY_TITLE_ONLY:
            logger.debug('Metadata policy: Read NFO file OFF | Scraper OFF')
            logger.debug('Metadata policy: Only cleaning ROM name.')
            self.metadata_action = ScrapeStrategy.ACTION_META_TITLE_ONLY

        elif self.scraper_settings.scrape_metadata_policy == constants.SCRAPE_POLICY_NFO_PREFERED:
            logger.debug('Metadata policy: Read NFO file ON | Scraper OFF')
            if NFO_file_found:
                logger.debug('Metadata policy: NFO file found.')
                self.metadata_action = ScrapeStrategy.ACTION_META_NFO_FILE
            else:
                logger.debug('Metadata policy: NFO file not found. Only cleaning ROM name')
                self.metadata_action = ScrapeStrategy.ACTION_META_TITLE_ONLY

        elif self.scraper_settings.scrape_metadata_policy == constants.SCRAPE_POLICY_NFO_AND_SCRAPE:
            logger.debug('Metadata policy: Read NFO file ON | Scraper ON')
            if NFO_file_found:
                logger.debug('Metadata policy: NFO file found. Scraper not used.')
                self.metadata_action = ScrapeStrategy.ACTION_META_NFO_FILE
            else:
                logger.debug('Metadata policy: NFO file not found. Using scraper.')
                self.metadata_action = ScrapeStrategy.ACTION_META_SCRAPER

        elif self.scraper_settings.scrape_metadata_policy == constants.SCRAPE_POLICY_SCRAPE_ONLY:
            logger.debug('Metadata policy: Read NFO file OFF | Scraper ON')
            logger.debug('Metadata policy: Using metadata scraper {}'.format(self.meta_scraper_obj.get_name()))
            self.metadata_action = ScrapeStrategy.ACTION_META_SCRAPER

        else:
            raise ValueError('Invalid scrape_metadata_policy value {0}'.format(self.scraper_settings.scrape_metadata_policy))
  
    # Determine the actions to be carried out by scanner_process_ROM_assets()
    def _scanner_process_ROM_assets_begin(self, ROM):
        logger.debug('ScrapeStrategy._scanner_process_ROM_assets_begin() Determining asset actions...')
        
        if self.asset_scraper_obj is None:
            logger.debug('ScrapeStrategy::_scanner_process_ROM_assets_begin() No asset scraper set, disabling asset scraping.')
            self.asset_action_list = { key.id:ScrapeStrategy.ACTION_ASSET_NONE for (key, value) in self.enabled_asset_list }
            return
        
        # --- Determine Asset action -------------------------------------------------------------
        # --- Search for local artwork/assets ---
        # Always look for local assets whatever the scanner settings. For unconfigured assets
        # local_asset_list will have the default database value empty string ''.
        self.local_asset_list = self.launcher.get_local_assets(ROM, self.enabled_asset_list) 
        self.asset_action_list = {}
        
        # Print information to the log
        if self.scraper_settings.scrape_assets_policy == constants.SCRAPE_POLICY_LOCAL_ONLY:
            logger.debug('Asset policy: Local images ON | Scraper OFF')
        elif self.scraper_settings.scrape_assets_policy == constants.SCRAPE_POLICY_LOCAL_AND_SCRAPE:
            logger.debug('Asset policy: Local images ON | Scraper ON')
        elif self.scraper_settings.scrape_assets_policy == constants.SCRAPE_POLICY_SCRAPE_ONLY:
            logger.debug('Asset policy: Local images OFF | Scraper ON')
        else:
            raise ValueError('Invalid scrape_assets_policy value {0}'.format(self.scraper_settings.scrape_assets_policy))
        # Process asset by asset (only enabled ones)
        for AInfo in self.enabled_asset_list:
            # Local artwork.
            if self.scraper_settings.scrape_assets_policy == constants.SCRAPE_POLICY_LOCAL_ONLY:
                if self.local_asset_list[AInfo.id]:
                    logger.debug('Local {0} FOUND'.format(AInfo.name))
                else:
                    logger.debug('Local {0} NOT found.'.format(AInfo.name))
                self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_LOCAL_ASSET
            # Local artwork + Scrapers.
            elif self.scraper_settings.scrape_assets_policy == constants.SCRAPE_POLICY_LOCAL_AND_SCRAPE:
                if self.local_asset_list[AInfo.id]:
                    logger.debug('Local {0} FOUND'.format(AInfo.name))
                    self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_LOCAL_ASSET
                elif self.asset_scraper_obj.supports_asset_ID(AInfo.id):
                    # Scrape only if scraper supports asset.
                    logger.debug('Local {0} NOT found. Scraping.'.format(AInfo.name))
                    self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_SCRAPER
                else:
                    logger.debug('Local {0} NOT found. No scraper support.'.format(AInfo.name))
                    self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_LOCAL_ASSET
            # Scrapers.
            elif self.scraper_settings.scrape_assets_policy == constants.SCRAPE_POLICY_SCRAPE_ONLY:
                # Scraper does not support asset but local asset found.
                if not self.asset_scraper_obj.supports_asset_ID(AInfo.id) and self.local_asset_list[AInfo.id]:
                    logger.debug('Scraper {} does not support {}. Using local asset.'.format(
                        self.asset_scraper_obj.get_name(), AInfo.name))
                    self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_LOCAL_ASSET
                # Scraper does not support asset and local asset not found.
                elif not self.asset_scraper_obj.supports_asset_ID(AInfo.id) and not self.local_asset_list[AInfo.id]:
                    logger.debug('Scraper {} does not support {}. Local asset not found.'.format(
                        self.asset_scraper_obj.get_name(), AInfo.name))
                    self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_LOCAL_ASSET
                # Scraper supports asset. Scrape wheter local asset is found or not.
                elif self.asset_scraper_obj.supports_asset_ID(AInfo.id):
                    logger.debug('Scraping {} with {}.'.format(AInfo.name, self.asset_scraper_obj.get_name()))
                    self.asset_action_list[AInfo.id] = ScrapeStrategy.ACTION_ASSET_SCRAPER
                else:
                    raise ValueError('Logical error')

    # Get a candidate game in the ROM scanner.
    # Returns nothing.
    def _scanner_get_candidate(self, ROM, ROM_checksums_FN, search_term, scraper_obj, status_dic):
        # --- Update scanner progress dialog ---
        if self.pdialogger.debugose:
            scraper_text = 'Searching games with scraper {}...'.format(scraper_obj.get_name())
            self.pdialog.updateMessage2(scraper_text)
        logger.debug('Searching games with scraper {}'.format(scraper_obj.get_name()))

        # * The scanner uses the cached ROM candidate always.
        # * If the candidate is empty it means it was previously searched and the scraper
        #   found no candidates. In this case, the context menu must be used to manually
        #   change the search string and set a valid candidate.
        ROM_path = ROM.get_file()
        if scraper_obj.check_candidates_cache(ROM_path, self.platform):
            logger.debug('ROM "{}" in candidates cache.'.format(ROM_path.getPath()))
            candidate = scraper_obj.retrieve_from_candidates_cache(ROM_path, self.platform)
            if not candidate:
                logger.debug('Candidate game is empty. ROM will not be scraped again by the scanner.')
            use_from_cache = True
        else:
            logger.debug('ROM "{}" NOT in candidates cache.'.format(ROM_path.getPath()))
            use_from_cache = False
        logger.debug('use_from_cache "{}"'.format(use_from_cache))

        if use_from_cache:
            scraper_obj.set_candidate_from_cache(ROM_path, self.platform)
        else:
            # Clear all caches to remove preexiting information, just in case user is rescraping.
            scraper_obj.clear_cache(ROM_path, self.platform)

            # --- Call scraper and get a list of games ---                
            candidates = scraper_obj.get_candidates(search_term, ROM_path, ROM_checksums_FN, self.platform, status_dic)
            # * If the scraper produced an error notification show it and continue scanner operation.
            # * Note that if many errors/exceptions happen (for example, network is down) then
            #   the scraper will disable itself after a number of errors and only a limited number
            #   of messages will be displayed.
            # * In the scanner treat any scraper error message as a Kodi OK dialog.
            # * Once the error is displayed reset status_dic
            if not status_dic['status']:
                self.pdialog.close()
                # Close error message dialog automatically 1 minute to keep scanning.
                # kodi_dialog_OK(status_dic['msg'])
                kodi.dialog_yesno_timer(status_dic['msg'], 60000)
                status_dic = kodi.new_status_dic('No error')
                self.pdialog.reopen()
            # * If candidates is None some kind of error/exception happened.
            # * None is also returned if the scraper is disabled (also no error in status_dic).
            # * Set the candidate to None in the scraper object so later calls to get_metadata()
            #   and get_assets() do not fail (they will return None immediately).
            # * It will NOT be introduced in the cache to be rescraped. Objects with None value are
            #   never introduced in the cache.
            if candidates is None:
                logger.debug('Error getting the candidate (None).')
                scraper_obj.set_candidate(ROM_path, self.platform, None)
                return
            # * If candidates list is empty scraper operation was correct but no candidate was
            # * found. In this case set the candidate in the scraper object to an empty
            # * dictionary and introduce it in the cache.
            if not candidates:
                logger.debug('Found no candidates after searching.')
                scraper_obj.set_candidate(ROM_path, self.platform, dict())
                return
            logger.debug('Scraper {} found {} candidate/s'.format(scraper_obj.get_name(), len(candidates)))

            # --- Choose game to download metadata ---
            if self.scraper_settings.game_selection_mode == constants.SCRAPE_AUTOMATIC:
                logger.debug('Metadata manual scraping')
                if len(candidates) == 1:
                    logger.debug('get_candidates() returned 1 game. Automatically selected.')
                    select_candidate_idx = 0
                else:
                    # Display game list found so user choses.
                    logger.debug('Metadata manual scraping. User chooses game.')
                    self.pdialog.close()
                    game_name_list = [candidate['display_name'] for candidate in candidates]
                    select_candidate_idx = kodi.ListDialog().select(
                        title='Select game for ROM {}'.format(ROM_path.getBaseNoExt()), options_list=game_name_list)
                    if select_candidate_idx < 0: select_candidate_idx = 0
                    self.pdialog.reopen()
            elif self.scraper_settings.game_selection_mode == constants.SCRAPE_MANUAL:
                logger.debug('Metadata automatic scraping. Selecting first result.')
                select_candidate_idx = 0
            else:
                raise ValueError('Invalid game_selection_mode {}'.format(self.scraper_settings.game_selection_mode))
            candidate = candidates[select_candidate_idx]

            # --- Set candidate. This will introduce it in the cache ---
            scraper_obj.set_candidate(ROM_path, self.platform, candidate)

    # Scraps ROM metadata in the ROM scanner.
    def _scanner_scrap_ROM_metadata(self, ROM):
        logger.debug('ScrapeStrategy._scanner_scrap_ROM_metadata() Scraping metadata...')

        # --- Update scanner progress dialog ---
        if self.pdialogger.debug:
            scraper_text = 'Scraping metadata with {}...'.format(self.meta_scraper_obj.get_name())
            self.pdialog.updateMessage2(scraper_text)

        # --- If no candidates available just clean the ROM Title and return ---
        if self.meta_scraper_obj.candidate is None:
            logger.debug('Medatada candidates is None. Cleaning ROM name only.')
            ROM_file = ROM.get_file()
            ROM.set_name(text.format_ROM_title(ROM_file.getBaseNoExt(), self.scan_clean_tags))
            return
        if not self.meta_scraper_obj.candidate:
            logger.debug('Medatada candidate is empty (no candidates found). Cleaning ROM name only.')
            ROM_file = ROM.get_file()
            ROM.set_name(text.format_ROM_title(ROM_file.getBaseNoExt(), self.scan_clean_tags))
            # Update the empty NFO file to mark the ROM as scraped and avoid rescraping
            # if launcher is scanned again.
            self._scanner_update_NFO_file(ROM)
            return

        # --- Grab metadata for selected game and put into ROM ---
        status_dic = kodi.new_status_dic('No error')
        game_data = self.meta_scraper_obj.get_metadata(status_dic)
        if not status_dic['status']:
            self.pdialog.close()
            # Close error message dialog automatically 1 minute to keep scanning.
            # kodi_dialog_OK(status_dic['msg'])
            kodi.dialog_yesno_timer(status_dic['msg'], 60000)
            self.pdialog.reopen()
            return
        scraper_applied = self._apply_candidate_on_metadata(game_data, ROM)
        self._scanner_update_NFO_file(ROM)

    # Update ROM NFO file after scraping.
    def _scanner_update_NFO_file(self, ROM):
        if self.scan_update_NFO_files:
            logger.debug('User wants to update NFO file after scraping.')
            fs_export_ROM_NFO(ROM.get_data_dic(), False)
        else:
            logger.debug('User wants to NOT update NFO file after scraping. Doing nothing.')

    #
    # Returns a valid filename of the downloaded scrapped image, filename of local image
    # or empty string if scraper finds nothing or download failed.
    #
    # @param asset_info [AssetInfo object]
    # @param local_asset_path: [str]
    # @param ROM: [Rom object]
    # @return: [str] Filename string with the asset path.
    def _scanner_scrap_ROM_asset(self, asset_info, local_asset_path, ROM):
        # --- Cached frequent used things ---
        asset_name = asset_info.name
        asset_dir_FN  = self.launcher.get_asset_path(asset_info)
        asset_path_noext_FN = asset_dir_FN + ROM.get_file().getBaseNoExt()
       
        t = 'ScrapeStrategy._scanner_scrap_ROM_asset() Scraping {} with scraper {} ------------------------------'
        logger.debug(t.format(asset_name, self.asset_scraper_obj.get_name()))
        status_dic = kodi.new_status_dic('No error')
        
        # By default always use local image if found in case scraper fails.
        ret_asset_path = local_asset_path
        logger.debug('local_asset_path "{}"'.format(local_asset_path))
        logger.debug('asset_path_noext "{}"'.format(asset_path_noext_FN.getPath()))

        # --- If no candidates available just clean the ROM Title and return ---
        if self.asset_scraper_obj.candidate is None:
            logger.debug('Asset candidate is None (previous error). Doing nothing.')
            return ret_asset_path
        if not self.asset_scraper_obj.candidate:
            logger.debug('Asset candidate is empty (no candidates found). Doing nothing.')
            return ret_asset_path

        # --- If scraper does not support particular asset return inmediately ---
        if not self.asset_scraper_obj.supports_asset_ID(asset_info.id):
            logger.debug('Scraper {} does not support asset {}.'.format(
                self.asset_scraper_obj.get_name(), asset_name))
            return ret_asset_path

        # --- Update scanner progress dialog ---
        if self.pdialogger.debugose:
            scraper_text = 'Getting {} images from {}...'.format(
                asset_name, self.asset_scraper_obj.get_name())
            self.pdialog.updateMessage2(scraper_text)

        # --- Grab list of images/assets for the selected candidate ---
        assetdata_list = self.asset_scraper_obj.get_assets(asset_info, status_dic)
        if not status_dic['status']:
            self.pdialog.close()
            # Close error message dialog automatically 1 minute to keep scanning.
            # kodi_dialog_OK(status_dic['msg'])
            kodi.dialog_yesno_timer(status_dic['msg'], 60000)
            status_dic = kodi.new_status_dic('No error')
            self.pdialog.reopen()
        if assetdata_list is None or not assetdata_list:
            # If scraper returns no images return current local asset.
            logger.debug('{} {} found no images.'.format(self.asset_scraper_obj.get_name(), asset_name))
            return ret_asset_path
        # logger.debug('{} scraper returned {} images.'.format(asset_name, len(assetdata_list)))

        # --- Semi-automatic scraping (user choses an image from a list) ---
        if self.scraper_settings.asset_selection_mode == constants.SCRAPE_MANUAL:
            # If there is a local image add it to the list and show it to the user
            local_asset_in_list_flag = False
            if local_asset_path:
                local_asset = {
                    'asset_ID'     : asset_info.id,
                    'display_name' : 'Current local image',
                    'url_thumb'    : local_asset_path.getPath(),
                }
                assetdata_list.insert(0, local_asset)
                local_asset_in_list_flag = True

            # Convert list returned by scraper into a list the select window uses.
            ListItem_list = []
            for item in assetdata_list:
                listitem_obj = xbmcgui.ListItem(label = item['display_name'], label2 = item['url_thumb'])
                listitem_obj.setArt({'icon' : item['url_thumb']})
                ListItem_list.append(listitem_obj)
            # ListItem_list has 1 or more elements at this point.
            # If assetdata_list has only 1 element do not show select dialog. Note that the
            # length of assetdata_list is 1 only if scraper returned 1 image and a local image
            # does not exist. If the scraper returned no images this point is never reached.
            if len(ListItem_list) == 1:
                image_selected_index = 0
            else:
                self.pdialog.close()
                image_selected_index = xbmcgui.Dialog().select(
                    'Select {0} asset'.format(asset_name), list = ListItem_list, useDetails = True)
                logger.debug('{0} dialog returned index {1}'.format(asset_name, image_selected_index))
                if image_selected_index < 0: image_selected_index = 0
                self.pdialog.reopen()
            # User chose to keep current asset.
            if local_asset_in_list_flag and image_selected_index == 0:
                logger.debug('User chose local asset. Returning.')
                return ret_asset_path
        # --- Automatic scraping. Pick first image. ---
        elif self.scraper_settings.asset_selection_mode == constants.SCRAPE_AUTOMATIC:
            image_selected_index = 0
        else:
            raise constants.AddonError('Invalid asset_selection_mode {0}'.format(self.scraper_settings.asset_selection_mode))

        # --- Download scraped image --------------------------------------------------------------
        selected_asset = assetdata_list[image_selected_index]

        # --- Resolve asset URL ---
        logger.debug('Resolving asset URL...')
        if self.pdialogger.debugose:
            scraper_text = 'Scraping {0} with {1} (Resolving URL...)'.format(
                asset_name, self.asset_scraper_obj.get_name())
            self.pdialog.updateMessage2(scraper_text)
        image_url, image_url_log = self.asset_scraper_obj.resolve_asset_URL(
            selected_asset, status_dic)
        if not status_dic['status']:
            self.pdialog.close()
            # Close error message dialog automatically 1 minute to keep scanning.
            # kodi_dialog_OK(status_dic['msg'])
            kodi.dialog_yesno_timer(status_dic['msg'], 60000)
            status_dic = kodi.new_status_dic('No error')
            self.pdialog.reopen()
        if image_url is None or not image_url:
            logger.debug('Error resolving URL')
            return ret_asset_path
        logger.debug('Resolved {0} to URL "{1}"'.format(asset_name, image_url_log))

        # --- Resolve URL extension ---
        logger.debug('Resolving asset URL extension...')
        image_ext = self.asset_scraper_obj.resolve_asset_URL_extension(
            selected_asset, image_url, status_dic)
        if not status_dic['status']:
            self.pdialog.close()
            # Close error message dialog automatically 1 minute to keep scanning.
            # kodi_dialog_OK(status_dic['msg'])
            kodi.dialog_yesno_timer(status_dic['msg'], 60000)
            status_dic = kodi.new_status_dic('No error')
            self.pdialog.reopen()
        if image_ext is None or not image_ext:
            logger.debug('Error resolving URL')
            return ret_asset_path
        logger.debug('Resolved URL extension "{}"'.format(image_ext))

        # --- Download image ---
        if self.pdialogger.debugose:
            scraper_text = 'Downloading {} from {}...'.format(
                asset_name, self.asset_scraper_obj.get_name())
            self.pdialog.updateMessage2(scraper_text)
        image_local_path = asset_path_noext_FN.append('.' + image_ext)
        logger.debug('Download  "{}"'.format(image_url_log))
        logger.debug('Into file "{}"'.format(image_local_path.getPath()))
        try:
            image_local_path = self.asset_scraper_obj.download_image(image_url, image_local_path)
        except:
            self.pdialog.close()
            # Close error message dialog automatically 1 minute to keep scanning.
            # kodi_dialog_OK(status_dic['msg'])
            kodi.dialog_yesno_timer('Cannot download {} image (Timeout)'.format(asset_name), 60000)
            self.pdialog.reopen()
        
        # --- Update Kodi cache with downloaded image ---
        # Recache only if local image is in the Kodi cache, this function takes care of that.
        # kodi_update_image_cache(image_path)

        # --- Check if downloaded image file is OK ---
        # For example, check if a PNG image is really a PNG, a JPG is really JPG, etc.
        # Check for 0 byte files and delete them.
        # Etc.

        # --- Return value is downloaded image ---
        return image_local_path
    
    # This function to be used in AEL 0.9.x series.
    #
    # @param gamedata: Dictionary with game data.
    # @param romdata: ROM/Launcher data dictionary.
    # @return: True if metadata is valid an applied, False otherwise.
    def _apply_candidate_on_metadata_old(self, gamedata, romdata, ROM):
        if not gamedata: return False

        # --- Put metadata into ROM/Launcher dictionary ---
        if self.scan_ignore_scrap_title:
            romdata['m_name'] = text.format_ROM_title(ROM.getBaseNoExt(), self.scan_clean_tags)
            logger.debug('User wants to ignore scraped name and use filename.')
        else:
            romdata['m_name'] = gamedata['title']
            logger.debug('User wants scrapped name and not filename.')
        logger.debug('Setting ROM name to "{0}"'.format(romdata['m_name']))
        romdata['m_year']      = gamedata['year']
        romdata['m_genre']     = gamedata['genre']
        romdata['m_developer'] = gamedata['developer']
        romdata['m_nplayers']  = gamedata['nplayers']
        romdata['m_esrb']      = gamedata['esrb']
        romdata['m_plot']      = gamedata['plot']

        return True

    # This function to be used in AEL 0.10.x series.
    #
    # @param gamedata: Dictionary with game data.
    # @param rom: ROM/Launcher object to apply metadata.
    # @return: True if metadata is valid an applied, False otherwise.
    def _apply_candidate_on_metadata(self, gamedata, rom):
        if not gamedata: return False

        # --- Put metadata into ROM/Launcher object ---
        if self.scan_ignore_scrap_title:
            rom_file = rom.get_file()
            rom_name = text.format_ROM_title(rom_file.getBaseNoExt(), self.scan_clean_tags)
            rom.set_name(rom_name)
            logger.debug("User wants to ignore scraper name. Setting name to '{0}'".format(rom_name))
        else:
            rom_name = gamedata['title']
            rom.set_name(rom_name)
            logger.debug("User wants scrapped name. Setting name to '{0}'".format(rom_name))

        rom.set_releaseyear(gamedata['year'])           # <year>
        rom.set_genre(gamedata['genre'])                # <genre>
        rom.set_developer(gamedata['developer'])        # <developer>
        rom.set_number_of_players(gamedata['nplayers']) # <nplayers>
        rom.set_esrb_rating(gamedata['esrb'])           # <esrb>
        rom.set_plot(gamedata['plot'])                  # <plot>

        return True
#
# Abstract base class for all scrapers (offline or online, metadata or asset).
# The scrapers are Launcher and ROM agnostic. All the required Launcher/ROM properties are
# stored in the strategy object.
#
class Scraper(object):
    __metaclass__ = abc.ABCMeta

    # --- Class variables ------------------------------------------------------------------------
    # When then number of network error/exceptions is bigger than this threshold the scraper
    # is deactivated. This is useful in the ROM Scanner to not flood the user with error
    # messages in case something is wrong (for example, the internet connection is broken or
    # the number of API calls is exceeded).
    EXCEPTION_COUNTER_THRESHOLD = 5
    
    # Maximum amount of retries of certain requests
    RETRY_THRESHOLD = 4

    # Disk cache types. These string will be part of the cache file names.
    CACHE_CANDIDATES = 'candidates'
    CACHE_METADATA   = 'metadata'
    CACHE_ASSETS     = 'assets'
    CACHE_INTERNAL   = 'internal'
    CACHE_LIST = [
        CACHE_CANDIDATES, CACHE_METADATA, CACHE_ASSETS, CACHE_INTERNAL,
    ]

    # TODO MOVE TO TGDB Scrpaer
    #GLOBAL_CACHE_TGDB_GENRES     = 'TGDB_genres'
    #GLOBAL_CACHE_TGDB_DEVELOPERS = 'TGDB_developers'
    #GLOBAL_CACHE_LIST = [
    #    GLOBAL_CACHE_TGDB_GENRES, GLOBAL_CACHE_TGDB_DEVELOPERS,
    #]

    JSON_indent = 1
    JSON_separators = (',', ':')

    # --- Constructor ----------------------------------------------------------------------------
    # @param settings: [dict] Addon settings.
    def __init__(self, settings:dict, fallbackScraper = None):
        self.settings = settings
        self.verbose_flag = False
        self.dump_file_flag = False # Dump DEBUG files only if this is true.
        self.dump_dir = None # Directory to dump DEBUG files.
        self.debug_checksums_flag = False
        # Record the number of network error/exceptions. If this number is bigger than a
        # threshold disable the scraper.
        self.exception_counter = 0
        # If this is True the scraper is internally disabled. A disabled scraper alwats returns
        # empty data like the NULL scraper.
        self.scraper_disabled = False
        # Directory to store on-disk scraper caches.
        self.scraper_cache_dir = settings['scraper_cache_dir']
        # Do not log here. Otherwise the same thing will be printed for every scraper instantiated.
        # logger.debug('Scraper.__init__() scraper_cache_dir "{}"'.format(self.scraper_cache_dir))

        self.last_http_call = datetime.now()
        
        # --- Disk caches ---
        self.disk_caches = {}
        self.disk_caches_loaded = {}
        self.disk_caches_dirty = {}
        for cache_name in Scraper.CACHE_LIST:
            self.disk_caches[cache_name] = {}
            self.disk_caches_loaded[cache_name] = False
            self.disk_caches_dirty[cache_name] = False
        # Candidate game is set with functions set_candidate_from_cache() or set_candidate()
        # and used by functions get_metadata() and get_assets()
        self.candidate = None

        # --- Global disk caches ---
        self.global_disk_caches = {}
        self.global_disk_caches_loaded = {}
        self.global_disk_caches_dirty = {}
        # for cache_name in Scraper.GLOBAL_CACHE_LIST:
        #     self.global_disk_caches[cache_name] = {}
        #     self.global_disk_caches_loaded[cache_name] = False
        #     self.global_disk_caches_dirty[cache_name] = False

    # --- Methods --------------------------------------------------------------------------------
    # Scraper is much more verbose (even more than AEL Debug level).
    def set_verbose_mode(self, verbose_flag):
        logger.debug('Scraper.set_verbose_mode() verbose_flag {0}'.format(verbose_flag))
        self.verbose_flag = verbose_flag

    # Dump scraper data into files for debugging. Used in the development scripts.
    def set_debug_file_dump(self, dump_file_flag, dump_dir):
        logger.debug('Scraper.set_debug_file_dump() dump_file_flag {0}'.format(dump_file_flag))
        logger.debug('Scraper.set_debug_file_dump() dump_dir {0}'.format(dump_dir))
        self.dump_file_flag = dump_file_flag
        self.dump_dir = dump_dir

    # ScreenScraper needs the checksum of the file scraped. This function sets the checksums
    # externally for debugging purposes, for example when debugging the scraper with
    # fake filenames.
    def set_debug_checksums(self, debug_checksums, crc_str = '', md5_str = '', sha1_str = '', size = 0):
        logger.debug('Scraper.set_debug_checksums() debug_checksums {0}'.format(debug_checksums))
        self.debug_checksums_flag = debug_checksums
        self.debug_crc  = crc_str
        self.debug_md5  = md5_str
        self.debug_sha1 = sha1_str
        self.debug_size = size

    # Dump dictionary as JSON file for debugging purposes.
    # This function is used internally by the scrapers if the flag self.dump_file_flag is True.
    def _dump_json_debug(self, file_name, data_dic):
        if not self.dump_file_flag: return
        file_path = os.path.join(self.dump_dir, file_name)
        if constants.SCRAPER_CACHE_HUMAN_JSON:
            json_str = json.dumps(data_dic, indent = 4, separators = (', ', ' : '))
        else:
            json_str = json.dumps(data_dic)
        io.FileName(file_path).writeAll(json_str)

    def _dump_file_debug(self, file_name, page_data):
        if not self.dump_file_flag: return
        file_path = os.path.join(self.dump_dir, file_name)
        io.FileName(file_path).writeAll(page_data)

    @abc.abstractmethod
    def get_id(self): pass
    
    @abc.abstractmethod
    def get_name(self): pass

    @abc.abstractmethod
    def get_filename(self): pass

    @abc.abstractmethod
    def supports_disk_cache(self): pass

    @abc.abstractmethod
    def supports_search_string(self): pass

    @abc.abstractmethod
    def supports_metadata_ID(self, metadata_ID): pass

    @abc.abstractmethod
    def supports_metadata(self): pass

    @abc.abstractmethod
    def supports_asset_ID(self, asset_ID): pass

    @abc.abstractmethod
    def supports_assets(self): pass

    # Check if the scraper is ready to work. For example, check if required API keys are
    # configured, etc. If there is some fatal errors then deactivate the scraper.
    #
    # @return: [dic] kodi_new_status_dic() status dictionary.
    @abc.abstractmethod
    def check_before_scraping(self, status_dic): pass

    # The *_candidates_cache_*() functions use the low level cache functions which are internal
    # to the Scraper object. The functions next are public, however.

    # Returns True if candidate is in disk cache, False otherwise.
    # Lazy loads candidate cache from disk.
    def check_candidates_cache(self, rom_FN, platform):
        self.cache_key = rom_FN.getBase()
        self.platform = platform

        return self._check_disk_cache(Scraper.CACHE_CANDIDATES, self.cache_key)

    # Not necesary to lazy load the cache because before calling this function
    # check_candidates_cache() must be called.
    def retrieve_from_candidates_cache(self, rom_FN:io.FileName, platform):
        self.cache_key = rom_FN.getBase()

        return self._retrieve_from_disk_cache(Scraper.CACHE_CANDIDATES, self.cache_key)

    def set_candidate_from_cache(self, rom_FN:io.FileName, platform):
        self.cache_key = rom_FN.getBase()
        self.platform  = platform
        self.candidate = self._retrieve_from_disk_cache(Scraper.CACHE_CANDIDATES, self.cache_key)

    def set_candidate(self, rom_FN:io.FileName, platform, candidate):
        self.cache_key = rom_FN.getBase()
        self.platform  = platform
        self.candidate = candidate
        logger.debug('Scrape.set_candidate() Setting "{}" "{}"'.format(self.cache_key, platform))
        # Do not introduce None candidates in the cache so the game will be rescraped later.
        # Keep the None candidate in the object internal variables so later calls to 
        # get_metadata() and get_assets() will know an error happened.
        if candidate is None: return
        self._update_disk_cache(Scraper.CACHE_CANDIDATES, self.cache_key, candidate)
        logger.debug('Scrape.set_candidate() Added "{}" to cache'.format(self.cache_key))

    # When the user decides to rescrape an item that was in the cache make sure all
    # the caches are purged.
    def clear_cache(self, rom_FN:io.FileName, platform):
        self.cache_key = rom_FN.getBase()
        self.platform = platform
        logger.debug('Scraper.clear_cache() Clearing caches "{}" "{}"'.format(
            self.cache_key, platform))
        for cache_type in Scraper.CACHE_LIST:
            if self._check_disk_cache(cache_type, self.cache_key):
                self._delete_from_disk_cache(cache_type, self.cache_key)

    # Only write to disk non-empty caches.
    # Only write to disk dirty caches. If cache has not been modified then do not write it.
    def flush_disk_cache(self, pdialog:kodi.ProgressDialog = None):
        # If scraper does not use disk cache (notably AEL Offline) return.
        if not self.supports_disk_cache():
            logger.debug('Scraper.flush_disk_cache() Scraper {} does not use disk cache.'.format(
                self.get_name()))
            return

        # Create progress dialog.
        num_steps = len(Scraper.CACHE_LIST) # + len(Scraper.GLOBAL_CACHE_LIST)
        step_count = 0
        if pdialog is not None:
            pdialog.startProgress('Flushing scraper disk caches...', num_steps)

        # --- Scraper caches ---
        logger.debug('Scraper.flush_disk_cache() Saving scraper {} disk cache...'.format(
            self.get_name()))
        for cache_type in Scraper.CACHE_LIST:
            if pdialog is not None:
                pdialog.updateProgress(step_count)
                step_count += 1

            # Skip unloaded caches
            if not self.disk_caches_loaded[cache_type]:
                logger.debug('Skipping {} (Unloaded)'.format(cache_type))
                continue
            # Skip empty caches
            if not self.disk_caches[cache_type]:
                logger.debug('Skipping {} (Empty)'.format(cache_type))
                continue
            # Skip clean caches.
            if not self.disk_caches_dirty[cache_type]:
                logger.debug('Skipping {} (Clean)'.format(cache_type))
                continue

            # Get JSON data.
            json_data = json.dumps(
                self.disk_caches[cache_type], ensure_ascii = False, sort_keys = True,
                indent = Scraper.JSON_indent, separators = Scraper.JSON_separators)

            # Write to disk
            json_file_path, json_fname = self._get_scraper_file_name(cache_type, self.platform)
            file = io.FileName(json_file_path)
            file.writeAll(json_data)
            
            # logger.debug('Saved "{}"'.format(json_file_path))
            logger.debug('Saved "<SCRAPER_CACHE_DIR>/{}"'.format(json_fname))

            # Cache written to disk is clean gain.
            self.disk_caches_dirty[cache_type] = False

        # --- Global caches ---
        # logger.debug('Scraper.flush_disk_cache() Saving scraper {} global disk cache...'.format(
        #         self.get_name()))
        # for cache_type in Scraper.GLOBAL_CACHE_LIST:
        #     if pdialog is not None:
        #         pdialog.updateProgress(step_count)
        #         step_count += 1

        #     # Skip unloaded caches
        #     if not self.global_disk_caches_loaded[cache_type]:
        #         logger.debug('Skipping global {} (Unloaded)'.format(cache_type))
        #         continue
        #     # Skip empty caches
        #     if not self.global_disk_caches[cache_type]:
        #         logger.debug('Skipping global {} (Empty)'.format(cache_type))
        #         continue
        #     # Skip clean caches.
        #     if not self.global_disk_caches_dirty[cache_type]:
        #         logger.debug('Skipping global {} (Clean)'.format(cache_type))
        #         continue

        #     # Get JSON data.
        #     json_data = json.dumps(
        #         self.global_disk_caches[cache_type], ensure_ascii = False, sort_keys = True,
        #         indent = Scraper.JSON_indent, separators = Scraper.JSON_separators)

        #     # Write to disk
        #     json_file_path, json_fname = self._get_global_file_name(cache_type)
        #     file = io.open(json_file_path, 'w', encoding = 'utf-8')
        #     file.write(unicode(json_data))
        #     file.close()
        #     # logger.debug('Saved global "{}"'.format(json_file_path))
        #     logger.debug('Saved global "<SCRAPER_CACHE_DIR>/{}"'.format(json_fname))

        #     # Cache written to disk is clean gain.
        #     self.global_disk_caches_dirty[cache_type] = False
        if pdialog is not None: pdialog.endProgress()

    # Search for candidates and return a list of dictionaries _new_candidate_dic().
    #
    # * This function is never cached. What is cached is the chosen candidate games.
    # * If no candidates found by the scraper return an empty list and status is True.
    # * If there is an error/exception (network error, bad data returned) return None,
    #   the cause is printed in the log, status is False and the status dictionary contains
    #   a user notification.
    # * The number of network error/exceptions is recorded internally by the scraper. If the
    #   number of errors is **bigger than a threshold**, **the scraper is deactivated** (no more
    #   errors reported in the future, just empty data is returned).
    # * If the scraper is overloaded (maximum number of API/web requests) it is considered and
    #   error and the scraper is internally deactivated immediately. The error message associated
    #   with the scraper overloading must be printed once like any other error.
    #
    # @param search_term: [str] String to be searched.
    # @param rom_FN: [FileName] Scraper will get whatever part of the filename they want.
    # @param rom_checksums_FN: [FileName] File to be used when computing checksums. For
    #                          multidisc ROMs rom_FN is a fake file but rom_checksums_FN is a real
    #                          file belonging to the set.
    # @param platform: [str] AEL platform.
    # @param status_dic: [dict] kodi_new_status_dic() status dictionary.
    # @return: [list] or None.
    @abc.abstractmethod
    def get_candidates(self, search_term, rom_FN, rom_checksums_FN, platform, status_dic): pass

    # Returns the metadata for a candidate (search result).
    #
    # * See comments in get_candidates()
    #
    # @param status_dic: [dict] kodi_new_status_dic() status dictionary.
    # @return: [dict] Dictionary self._new_gamedata_dic(). If no metadata found (very unlikely)
    #          then a dictionary with default values is returned. If there is an error/exception
    #          None is returned, the cause printed in the log and status_dic has a message to show.
    @abc.abstractmethod
    def get_metadata(self, status_dic): pass

    # Returns a list of assets for a candidate (search result).
    #
    # * See comments in get_candidates()
    #
    # @param status_dic: [dict] kodi_new_status_dic() status dictionary.
    # @return: [list] List of _new_assetdata_dic() dictionaries. If no assets found then an empty
    #          list is returned. If there is an error/exception None is returned, the cause printed
    #          in the log and status_dic has a message to show.
    @abc.abstractmethod
    def get_assets(self, asset_info, status_dic): pass

    # When returning the asset list with get_assets(), some sites return thumbnails images
    # because the real assets are on a single dedicated page. For this sites, resolve_asset_URL()
    # returns the true, full size URL of the asset.
    #
    # Other scrapers, for example MobyGames, return both the thumbnail and the true asset URLs
    # in get_assets(). In such case, the implementation of this method is trivial.
    #
    # @param selected_asset: 
    # @param status_dic: [dict] kodi_new_status_dic() status dictionary.
    # @return: [tuple of strings] or None 
    #          First item, string with the URL to download the asset.
    #          Second item, string with the URL for printing in logs. URL may have sensitive
    #          information in some scrapers.
    #          None is returned in case of error and status_dic updated.
    @abc.abstractmethod
    def resolve_asset_URL(self, selected_asset, status_dic): pass

    # Get the URL image extension. In some scrapers the type of asset cannot be obtained by
    # the asset URL and must be resolved to save the asset in the filesystem.
    #
    # @param selected_asset: 
    # @param image_url: 
    # @param status_dic: [dict] kodi_new_status_dic() status dictionary.
    # @return: [str] String with the image extension in lowercase 'png', 'jpg', etc.
    #          None is returned in case or error/exception and status_dic updated.
    @abc.abstractmethod
    def resolve_asset_URL_extension(self, selected_asset, image_url, status_dic): pass

    # Downloads an image from the given url to the local path.
    # Can overwrite this method in scraper implementation to support extra actions, like
    # request throttling.
    def download_image(self, image_url, image_local_path):
        # net_download_img() never prints URLs or paths.
        net.download_img(image_url, image_local_path)
        return image_local_path

    # Not used now. candidate['id'] is used as hash value for the whole candidate dictionary.
    # candidate['id'] must be unique for each game.
    # def _dictionary_hash(self, my_dict):
    #     return hash(frozenset(sorted(my_dict.items())))

    # Nested dictionaries are not allowed. All the dictionaries here must be "hashable".
    # If your dictionary is not nested, you could make a frozenset with the dict's items
    # and use hash():
    #
    # hash(frozenset(sorted(my_dict.items())))
    #
    # This is much less computationally intensive than generating the JSON string
    # or representation of the dictionary.
    # See https://stackoverflow.com/questions/5884066/hashing-a-dictionary
    def _new_candidate_dic(self):
        return {
            'id'               : '',
            'display_name'     : '',
            'platform'         : '',
            'scraper_platform' : '',
            'order'            : 0,
        }

    def _new_gamedata_dic(self):
        return {
            'title'     : '',
            'year'      : '',
            'genre'     : '',
            'developer' : '',
            'nplayers'  : '',
            'esrb'      : '',
            'plot'      : ''
        }

    # url_thumb is always returned by get_assets().
    # url is returned by resolve_asset_URL().
    # Note that some scrapers (MobyGames) return both url_thumb and url in get_assets(). Always
    # call resolve_asset_URL() for compabilitity with all scrapers.
    def _new_assetdata_dic(self):
        return {
            'asset_ID'     : None,
            'display_name' : '',
            'url_thumb'    : '',
            'url'          : '',
            'downloadable' : True
        }

    # This functions is called when an error that is not an exception and needs to increase
    # the scraper error limit happens.
    # All messages generated in the scrapers are KODI_MESSAGE_DIALOG.
    def _handle_error(self, status_dic, user_msg):
        # Print error message to the log.
        logger.error('Scraper._handle_error() user_msg "{}"'.format(user_msg))

        # Fill in the status dictionary so the error message will be propagated up in the
        # stack and the error message printed in the GUI.
        status_dic['status'] = False
        status_dic['dialog'] = kodi.KODI_MESSAGE_DIALOG
        status_dic['msg'] = user_msg
        
        # Record the number of error/exceptions produced in the scraper and disable the scraper
        # if the number of errors is higher than a threshold.
        self.exception_counter += 1
        if self.exception_counter > Scraper.EXCEPTION_COUNTER_THRESHOLD:
            err_m = 'Maximum number of errors exceeded. Disabling scraper.'
            logger.error(err_m)
            self.scraper_disabled = True
            # Replace error message witht the one that the scraper is disabled.
            status_dic['msg'] = err_m

    # This function is called when an exception in the scraper code happens.
    # All messages from the scrapers are KODI_MESSAGE_DIALOG.
    def _handle_exception(self, ex, status_dic, user_msg):
        logger.error('(Exception) Object type "{}"'.format(type(ex)))
        logger.error('(Exception) Message "{}"'.format(str(ex)))
        self._handle_error(status_dic, user_msg)

    # --- Private disk cache functions -----------------------------------------------------------
    def _get_scraper_file_name(self, cache_type, platform):
        scraper_filename = self.get_filename()
        json_fname = scraper_filename + '__' + platform + '__' + cache_type + '.json'
        json_full_path = os.path.join(self.scraper_cache_dir, json_fname)

        return json_full_path, json_fname

    def _lazy_load_disk_cache(self, cache_type):
        if not self.disk_caches_loaded[cache_type]:
            self._load_disk_cache(cache_type, self.platform)

    def _load_disk_cache(self, cache_type, platform):
        # --- Get filename ---
        json_file_path, json_fname = self._get_scraper_file_name(cache_type, platform)
        logger.debug('Scraper._load_disk_cache() Loading cache "{}"'.format(cache_type))

        # --- Load cache if file exists ---
        if os.path.isfile(json_file_path):
            file = open(json_file_path)
            file_contents = file.read()
            file.close()
            self.disk_caches[cache_type] = json.loads(file_contents)
            # logger.debug('Loaded "{}"'.format(json_file_path))
            logger.debug('Loaded "<SCRAPER_CACHE_DIR>/{}"'.format(json_fname))
        else:
            logger.debug('Cache file not found. Resetting cache.')
            self.disk_caches[cache_type] = {}
        self.disk_caches_loaded[cache_type] = True
        self.disk_caches_dirty[cache_type] = False

    # Returns True if item is in the cache, False otherwise.
    # Lazy loads cache files from disk.
    def _check_disk_cache(self, cache_type, cache_key):
        self._lazy_load_disk_cache(cache_type)

        return True if cache_key in self.disk_caches[cache_type] else False

    # _check_disk_cache() must be called before this.
    def _retrieve_from_disk_cache(self, cache_type, cache_key):
        return self.disk_caches[cache_type][cache_key]

    # _check_disk_cache() must be called before this.
    def _delete_from_disk_cache(self, cache_type, cache_key):
        del self.disk_caches[cache_type][cache_key]
        self.disk_caches_dirty[cache_type] = True

    # Lazy loading should be done here because the internal cache for ScreenScraper
    # could be updated withouth being loaded first with _check_disk_cache().
    def _update_disk_cache(self, cache_type, cache_key, data):
        self._lazy_load_disk_cache(cache_type)
        self.disk_caches[cache_type][cache_key] = data
        self.disk_caches_dirty[cache_type] = True

    # --- Private global disk caches -------------------------------------------------------------
    def _get_global_file_name(self, cache_type):
        json_fname = cache_type + '.json'
        json_full_path = os.path.join(self.scraper_cache_dir, json_fname).decode('utf-8')

        return json_full_path, json_fname

    def _lazy_load_global_disk_cache(self, cache_type):
        if not self.global_disk_caches_loaded[cache_type]:
            self._load_global_cache(cache_type)

    def _load_global_cache(self, cache_type):
        # --- Get filename ---
        json_file_path, json_fname = self._get_global_file_name(cache_type)
        logger.debug('Scraper._load_global_cache() Loading cache "{}"'.format(cache_type))

        # --- Load cache if file exists ---
        if os.path.isfile(json_file_path):
            file = open(json_file_path)
            file_contents = file.read()
            file.close()
            self.global_disk_caches[cache_type] = json.loads(file_contents)
            # logger.debug('Loaded "{}"'.format(json_file_path))
            logger.debug('Loaded "<SCRAPER_CACHE_DIR>/{}"'.format(json_fname))
        else:
            logger.debug('Cache file not found. Resetting cache.')
            self.global_disk_caches[cache_type] = {}
        self.global_disk_caches_loaded[cache_type] = True
        self.global_disk_caches_dirty[cache_type] = False

    def _check_global_cache(self, cache_type):
        self._lazy_load_global_disk_cache(cache_type)

        return self.global_disk_caches[cache_type]

    # _check_global_cache() must be called before this.
    def _retrieve_global_cache(self, cache_type):
        return self.global_disk_caches[cache_type]

    # _check_global_cache() must be called before this.
    def _reset_global_cache(self, cache_type):
        self.global_disk_caches[cache_type] = {}
        self.global_disk_caches_dirty[cache_type] = True

    def _update_global_cache(self, cache_type, data):
        self._lazy_load_global_disk_cache(cache_type)
        self.global_disk_caches[cache_type] = data
        self.global_disk_caches_dirty[cache_type] = True

    # Generic waiting method to avoid too many requests
    # and website abuse. 
    def _wait_for_API_request(self, wait_time_in_miliseconds = 1000):
        if wait_time_in_miliseconds == 0:
            return
        
        # Make sure we dont go over the TooManyRequests limit of 1 second.
        now = datetime.now()
        if (now - self.last_http_call).total_seconds() * 1000 < wait_time_in_miliseconds:
            logger.debug('Scraper._wait_for_API_request() Sleeping {}ms to avoid overloading...'.format(wait_time_in_miliseconds))
            time.sleep(wait_time_in_miliseconds / 1000)
  