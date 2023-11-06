# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/load.ipynb.

# %% auto 0
__all__ = ['read_gamma_image', 'write_gamma_image', 'read_gamma_plist', 'write_gamma_plist', 'de_load_gamma_flatten_rslc',
           'de_load_gamma_lat_lon_hgt', 'de_load_gamma_look_vector', 'de_load_gamma_range', 'de_load_gamma_metadata']

# %% ../../nbs/CLI/load.ipynb 5
import glob
from pathlib import Path
import tempfile
import re
import os
import logging
import math
import toml
import zarr

import numpy as np
import numba
import pandas as pd
from scipy.constants import speed_of_light
from dask import array as da
from dask import delayed
from dask.distributed import Client, LocalCluster, progress

from .utils.logging import de_logger, log_args

from fastcore.script import call_parse

# %% ../../nbs/CLI/load.ipynb 6
def _rdc_width_nlines(image_par):
    """get slc width and number of lines.
    """
    with open(image_par) as f:
        for line in f:
            if re.search('range_samples',line):
                rdc_width = int(line.split()[1])
            if re.search('azimuth_lines',line):
                rdc_nlines = int(line.split()[1])
    return rdc_width, rdc_nlines

# %% ../../nbs/CLI/load.ipynb 7
def _geo_width_nlines(dem_par):
    """get dem width and number of lines.
    """
    with open(dem_par) as f:
        for line in f:
            if re.search('width',line):
                geo_width = int(line.split()[1])
            if re.search('nlines',line):
                geo_nlines = int(line.split()[1])
    return geo_width, geo_nlines

# %% ../../nbs/CLI/load.ipynb 8
def _cor_pos_dem(dem_par):
    """get corner lat and lon and post lat and lon
    """
    with open(dem_par) as f:
        for line in f:
            if re.search('corner_lat',line):
                cor_lat = float(line.split()[1])
            if re.search('corner_lon',line):
                cor_lon = float(line.split()[1])
            if re.search('post_lat',line):
                pos_lat = float(line.split()[1])
            if re.search('post_lon',line):
                pos_lon = float(line.split()[1])
    return cor_lat, cor_lon, pos_lat, pos_lon

# %% ../../nbs/CLI/load.ipynb 9
def _fetch_slc_par_date(rslc_dir,# str / Path
                       ):
    rslc_dir = Path(rslc_dir)
    rslcs = []
    rslc_pars = []
    dates = []
    for rslc in sorted(rslc_dir.glob('*.rslc')):
        rslc_par = rslc.parent / (rslc.name + '.par')
        assert rslc_par.exists(), f'{str(rslc_par)} not exists!'
        date = rslc.stem

        rslcs.append(rslc)
        rslc_pars.append(rslc_par)
        dates.append(date)
    rslcs_df = pd.DataFrame({'date':dates,'rslc':rslcs,'par':rslc_pars})
    return rslcs_df

# %% ../../nbs/CLI/load.ipynb 10
def read_gamma_image(imag:str, # gamma raster data
                     width:int, # data width
                     dtype:str='float', # data format, only 'float' and 'fcomplex' are supported
                     y0:int=0, # line number to start reading
                     ny:int=None, # number of lines to read, default: to the last line
                    ):
    # gpu:bool=False, # return a cupy array if true 
    # !! nvidia gpu do not support big endian data, so no way to directly read it
    '''read gamma image into numpy array.'''
    if dtype == 'float':
        dt = '>f4'
    elif dtype == 'fcomplex':
        dt = '>c8'
    elif dtype == 'int':
        dt = '>i4'
    elif dtype =='double':
        dt = '>f8'
    else: raise ValueError('Unsupported data type')

    with open(imag,"rb") as datf:
        datf.seek(0,os.SEEK_END)
        size = datf.tell()
    n_byte = int(dt[-1]) # number of byte per data point
    nlines = int(size / n_byte / width)
    assert y0 <= nlines, 'y0 is larger than height.'
    if ny is None: ny = nlines-y0
    assert y0+ny <= nlines, 'y0+ny is larger than height.'
    offset = y0*width*n_byte
    count = ny*width*n_byte
    # if gpu:
    #     import cupy as cp
    #     import kvikio
    #     import kvikio.zarr
    #     with kvikio.CuFile(imag,'rb') as cufile:
    #         gpu_dt = dt.replace('>','=')
    #         data = cp.empty((ny,width),dtype=dt)
    #         cufile.read(data,size=count,file_offset=offset)
    #     return data
    # else:
    with open(imag,'rb') as datf:
        data = np.fromfile(datf,dtype=dt,offset=offset,count=ny*width)
    data = data.astype(data.dtype.newbyteorder('native'))
    return data.reshape(-1,width)

# %% ../../nbs/CLI/load.ipynb 11
def write_gamma_image(imag,path):
    imag = imag.astype(imag.dtype.newbyteorder('big'))
    imag.tofile(path)

# %% ../../nbs/CLI/load.ipynb 12
def read_gamma_plist(plist:str,dtype='int'):
    return read_gamma_image(plist,width=2,dtype=dtype)

# %% ../../nbs/CLI/load.ipynb 13
def write_gamma_plist(imag,path):
    return write_gamma_image(imag,path)

# %% ../../nbs/CLI/load.ipynb 17
@numba.jit(nopython=True, cache=True,parallel=True,nogil=True)
def _flatten_rslc(sim_orb,rslc):
    y = np.empty(rslc.shape, rslc.dtype)
    for i in numba.prange(len(rslc)):
        y[i] = np.exp(sim_orb[i]*1j)*rslc[i]
    return y

# %% ../../nbs/CLI/load.ipynb 19
@call_parse
@log_args
@de_logger
def de_load_gamma_flatten_rslc(rslc_dir:str, # gamma rslc directory, the name of the rslc and their par files should be '????????.rslc' and '????????.rslc.par'
                               reference:str, # reference date, eg: '20200202'
                               hgt:str, # the DEM in radar coordinate
                               scratch_dir:str, # directory for preserve gamma intermediate files
                               rslc_zarr:str, # output, the flattened rslcs stack in zarr format
                               az_chunk_size:int=None, # rslcs stack azimuth chunk size, azimuth number of lines by default (one chunk)
                               r_chunk_size:int=None, # rslcs stack range chunk size
                              ):
    '''Generate flatten rslc data from gamma command and convert them into zarr format.
    The shape of hgt should be same as one rslc image, i.e. the hgt file is generated with 1 by 1 look geocoding.
    '''
    logger = logging.getLogger(__name__)
    rslcs = _fetch_slc_par_date(rslc_dir)
    with pd.option_context('display.max_colwidth', 0):
        logger.info('rslc found: \n'+str(rslcs))
    rslc_pars = rslcs['par'].to_list()
    dates = rslcs['date'].to_list()
    rslcs = rslcs['rslc'].to_list()

    reference_idx = dates.index(reference)
    ref_rslc = rslcs[reference_idx]
    ref_rslc_par = rslc_pars[reference_idx]
    hgt = Path(hgt)

    n_image = len(rslcs)
    width,nlines = _rdc_width_nlines(ref_rslc_par)
    if az_chunk_size is None: az_chunk_size = nlines
    if r_chunk_size is None: r_chunk_size = width
    logger.info(f'number of images: {n_image}.')
    logger.info(f'image number of lines: {nlines}.')
    logger.info(f'image width: {width}.')

    logger.info('run gamma command to generate required data for flattened rslcs:')
        
    scratch_dir = Path(scratch_dir)
    scratch_dir.mkdir(exist_ok=True)
    sim_orbs = []
    for i,(date,rslc,rslc_par) in enumerate(zip(dates,rslcs,rslc_pars)):
        off_par = scratch_dir/(reference+'_'+date+'.off')
        create_offset_command = f'create_offset {str(ref_rslc_par)} {str(rslc_par)} {str(off_par)} 1 1 1 0 >> {str(scratch_dir/"gamma.log")}'
        logger.info('run command: ' + create_offset_command)
        os.system(create_offset_command)
        sim_orb = scratch_dir/(reference+'_'+date+'.sim_orb')
        phase_sim_orb_command = f'phase_sim_orb {str(ref_rslc_par)} {str(rslc_par)} {str(off_par)} {str(hgt)} {str(sim_orb)} {str(ref_rslc_par)} - - 1 1 >> {str(scratch_dir/"gamma.log")}'
        if sim_orb.exists():
            logger.info(f'{sim_orb} exists. skip runing {phase_sim_orb_command}')
        else:
            logger.info('run command: ' + phase_sim_orb_command)
            os.system(phase_sim_orb_command)
        sim_orbs.append(sim_orb)
    logger.info('gamma command finished.')
    logger.info('using dask to load data in gamma binary format to calculate flatten rslcs and save it to zarr.')
    logger.info('starting dask local cluster.')
    with LocalCluster(n_workers=1, threads_per_worker=3) as cluster, Client(cluster) as client:
        logger.info('dask local cluster started.')
        read_gamma_image_delayed = delayed(read_gamma_image, pure=True)

        n_az_chunk = math.ceil(nlines/az_chunk_size)
        lazy_rslcs = np.empty((n_az_chunk,1,n_image),dtype=object)
        lazy_sim_orbs = np.empty((n_az_chunk,1,n_image),dtype=object)
        lazy_flatten_rslcs = np.empty_like(lazy_rslcs)
        for k, rslc in enumerate(rslcs):
            for i in range(n_az_chunk):
                y0 = i*az_chunk_size
                ny =  nlines-y0 if (i == n_az_chunk-1) else az_chunk_size 
                lazy_rslcs[i,0,k] = read_gamma_image_delayed(rslc,width,dtype='fcomplex',y0=y0,ny=ny)
                lazy_sim_orbs[i,0,k] = read_gamma_image_delayed(sim_orbs[k],width, dtype='float',y0=y0,ny=ny)
                lazy_flatten_rslcs[i,0,k] = delayed(_flatten_rslc,pure=True,nout=1)(lazy_sim_orbs[i,0,k],lazy_rslcs[i,0,k])
                lazy_flatten_rslcs[i,0,k] = (da.from_delayed(lazy_flatten_rslcs[i,0,k],shape=(ny,width),meta=np.array((),dtype=np.complex64))).reshape(ny,width,1)
        flatten_rslcs_data = da.block(lazy_flatten_rslcs.tolist())

        flatten_rslcs_data = flatten_rslcs_data.rechunk((az_chunk_size,r_chunk_size,1))
        logger.darr_info('flattened rslc', flatten_rslcs_data) 
        _flatten_rslcs_data = flatten_rslcs_data.to_zarr(rslc_zarr,overwrite=True,compute=False)

        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist(_flatten_rslcs_data)
        progress(futures,notebook=False)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')

# %% ../../nbs/CLI/load.ipynb 25
@call_parse
@log_args
def de_load_gamma_lat_lon_hgt(diff_par:str, # geocoding diff_par,using the simulated image as reference
                              rslc_par:str, # par file of the reference rslc
                              dem_par:str, # dem par
                              hgt:str, # DEM in radar coordinate
                              scratch_dir:str, # directory for preserve gamma intermediate files
                              lat_zarr:str, # output, latitude zarr
                              lon_zarr:str, # output, longitude zarr
                              hgt_zarr:str, # output, height zarr
                              az_chunk_size:int=None, # azimuth chunk size, default (height)
                              r_chunk_size:int=None, # range chunk size, default (width)
):
    '''
    Function to load longitude and latitude from gamma binary format to zarr.
    '''
    logger = logging.getLogger(__name__)
    geo_width = _geo_width_nlines(dem_par)[0]
    rdc_width, rdc_nlines = _rdc_width_nlines(rslc_par)
    if az_chunk_size is None: az_chunk_size = rdc_nlines
    if r_chunk_size is None: r_chunk_size = rdc_width
    logger.info(f'image shape: ({rdc_nlines},{rdc_width})')

    lat_data = zarr.open(lat_zarr,mode='w',shape=(rdc_nlines,rdc_width),chunks = (az_chunk_size,r_chunk_size), dtype=np.float64)
    lon_data = zarr.open(lon_zarr,mode='w',shape=(rdc_nlines,rdc_width),chunks = (az_chunk_size,r_chunk_size), dtype=np.float64)
    hgt_data = zarr.open(hgt_zarr,mode='w',shape=(rdc_nlines,rdc_width),chunks = (az_chunk_size,r_chunk_size), dtype=np.float32)

    scratch_dir = Path(scratch_dir)
    scratch_dir.mkdir(exist_ok=True)
    logger.info('run gamma command to generate longitude, latitude and height:')

    plist = scratch_dir/'plist'
    command =f"mkgrid {str(plist)} {rdc_width} {rdc_nlines} 1 1 >> {str(scratch_dir/'gamma.log')}"
    if plist.exists():
        logger.info(f'{plist} exists. skip runing {command}')
    else:
        # pt_i = np.arange(rdc_width,dtype=np.int32)
        # pt_j = np.arange(rdc_nlines,dtype=np.int32)
        # pt_ii,pt_jj = np.meshgrid(pt_i,pt_j)
        # pt_ij = np.stack((pt_ii,pt_jj),axis=-1)
        # write_gamma_plist(pt_ij,scratch_dir/'plist')
        logger.info('run command: ' + command)
        os.system(command)
        logger.info('gamma command finished.')

    phgt_wgs84 = scratch_dir/'phgt_wgs84'
    command = f"pt2geo {str(plist)} - {rslc_par} - {hgt} {dem_par} {diff_par} 1 1 - - {str(scratch_dir/'plat_lon')} {str(phgt_wgs84)} >> {str(scratch_dir/'gamma.log')}"
    if phgt_wgs84.exists():
        logger.info(f'{phgt_wgs84} exists. skip runing {command}')
    else:
        logger.info('run command: ' + command)
        os.system(command)
        logger.info('gamma command finished.')
    logger.info('writing zarr file.')
    ptlonlat = read_gamma_plist(str(scratch_dir/'plat_lon'),dtype='double')
    lon_data[:], lat_data[:] = ptlonlat[:,0].reshape(rdc_nlines,rdc_width),ptlonlat[:,1].reshape(rdc_nlines,rdc_width)
    hgt_data[:] = read_gamma_image(str(phgt_wgs84),width=rdc_width,dtype='float')
    logger.info('write done.')

# %% ../../nbs/CLI/load.ipynb 31
@call_parse
@log_args
def de_load_gamma_look_vector(theta:str, # elevation angle
                              phi:str, # orientation angle
                              lt:str, # lookup table
                              rslc_par:str, # par file of the reference rslc
                              dem_par:str, # dem par
                              scratch_dir:str, # directory for preserve gamma intermediate files
                              theta_zarr:str, # output, elevation angle zarr
                              phi_zarr:str, # output, orientation angle zarr
                              az_chunk_size:int=None, # azimuth chunk size, default (height)
                              r_chunk_size:int=None, # range chunk size, default (width)
                             ):
    '''
    Load look vector (elevation angle and orientation angle) in map geometry
    from gamma binary format to look vector in radar geometry zarr file.
    The two input data should be generated with the `look_vector` gamma command.
    '''
    logger = logging.getLogger(__name__)
    geo_width = _geo_width_nlines(dem_par)[0]
    rdc_width, rdc_nlines = _rdc_width_nlines(rslc_par)
    if az_chunk_size is None: az_chunk_size = rdc_nlines
    if r_chunk_size is None: r_chunk_size = rdc_width
    logger.info(f'image shape: ({rdc_nlines},{rdc_width})')

    theta_data = zarr.open(theta_zarr,mode='w',shape=(rdc_nlines,rdc_width),chunks = (az_chunk_size,r_chunk_size), dtype=np.float32)
    phi_data = zarr.open(phi_zarr,mode='w',shape=(rdc_nlines,rdc_width),chunks = (az_chunk_size,r_chunk_size), dtype=np.float32)

    scratch_dir = Path(scratch_dir)
    scratch_dir.mkdir(exist_ok=True)

    theta_rdc = scratch_dir/'theta_rdc'
    command = f'geocode {lt} {theta} {geo_width} {str(theta_rdc)} {rdc_width} {rdc_nlines} >> {scratch_dir/"gamma.log"}'
    if theta_rdc.exists():
        logger.info(f'{theta_rdc} exists. skip runing {command}')
    else:
        logger.info('run gamma command to generate elevation angle in range doppler coordinate:')
        logger.info('run command: ' + command)
        os.system(command)
        logger.info('gamma command finished.')
    logger.info('writing data.')
    theta_data[:] = read_gamma_image(theta_rdc,rdc_width,dtype='float')

    phi_rdc = scratch_dir/'phi_rdc'
    command = f'geocode {lt} {phi} {geo_width} {str(phi_rdc)} {rdc_width} {rdc_nlines} >> {scratch_dir/"gamma.log"}'
    if phi_rdc.exists():
        logger.info(f'{phi_rdc} exists. skip runing {command}')
    else:
        logger.info('run gamma command to generate orientation angle in range doppler coordinate:')
        logger.info('run command: ' + command)
        os.system(command)
        logger.info('gamma command finished.')
    logger.info('writing data.')
    phi_data[:] = read_gamma_image(phi_rdc,rdc_width,dtype='float')
    logger.info('Done.')

# %% ../../nbs/CLI/load.ipynb 37
@call_parse
@log_args
def de_load_gamma_range(rslc_par:str, # par file of one rslc
                        range_zarr:str, # output, range distance zarr
                        az_chunk_size:int=None, # azimuth chunk size, default (height)
                        r_chunk_size:int=None, # range chunk size, default (width)
                       ):
    '''
    Generate slant range distance and save to zarr.
    '''
    logger = logging.getLogger(__name__)
    rdc_width, rdc_nlines = _rdc_width_nlines(rslc_par)
    if az_chunk_size is None: az_chunk_size = rdc_nlines
    if r_chunk_size is None: r_chunk_size = rdc_width
    logger.info(f'image shape: ({rdc_nlines},{rdc_width})')
    with open(rslc_par) as f:
        for line in f:
            if re.search('near_range_slc',line):
                rho0 = float(line.split()[1])
            if re.search('range_pixel_spacing',line):
                d_rho = float(line.split()[1])

    logger.info('Calculating slant range distance.')
    rho1d = np.arange(rdc_width)*d_rho+rho0
    rho2d = np.tile(rho1d,(rdc_nlines,1))
    range_data = zarr.open(range_zarr,mode='w',shape=(rdc_nlines,rdc_width),chunks = (az_chunk_size,r_chunk_size), dtype=np.float32)
    logger.info('writing data.')
    range_data[:] = rho2d
    logger.info('Done.')

# %% ../../nbs/CLI/load.ipynb 42
@call_parse
@log_args
def de_load_gamma_metadata(rslc_dir:str, # # gamma rslc directory, the name of the rslc and their par files should be '????????.rslc' and '????????.rslc.par'
                           reference:str, # reference date, eg: '20200202'
                           meta_file:str, # text toml file for meta data
):
    '''
    Load necessary metadata into a toml file.
    '''
    meta = dict()
    rslc_dir = Path(rslc_dir)
    dates = []
    logger = logging.getLogger(__name__)
    for par_file in sorted(rslc_dir.glob('*.rslc.par')):
        dates.append(par_file.name[:8])
    meta['dates'] = dates

    with open(rslc_dir/(reference+'.rslc.par')) as f:
        for line in f:
            if re.search('radar_frequency',line):
                radar_f = float(line.split()[1])
                rdr_wavelen = speed_of_light/radar_f
                logger.info('Fetching randar wavelength')
            if re.search('heading',line):
                heading = float(line.split()[1])
                logger.info('Fetching heading angle')
            if re.search('range_pixel_spacing',line):
                dr = float(line.split()[1])
                logger.info('Fetching range pixel spacing')
            if re.search('azimuth_pixel_spacing',line):
                daz = float(line.split()[1])
                logger.info('fetching azimuth pixel spacing')

    meta['radar_wavelength'] = rdr_wavelen
    meta['range_pixel_spacing'] = dr
    meta['azimuth_pixel_spacing'] = daz

    with tempfile.TemporaryDirectory() as temp_dir:        
        temp_dir = Path(temp_dir)
        slc_tab = temp_dir/'slc_tab'
        bperp = temp_dir/'bperp'
        itab = temp_dir/'itab'
        
        tab_content = ''
        for date in dates:
            tab_content += str(rslc_dir/(date+'.rslc'))
            tab_content += '      '
            tab_content += str(rslc_dir/(date+'.rslc.par'))
            tab_content += '\n'
        slc_tab.write_text(tab_content)

        logger.info('Run gamma command to calculate baseline:')
        command = f"base_calc {str(slc_tab)} {str(rslc_dir/(reference+'.rslc.par'))} {str(bperp)} {str(itab)} - > {temp_dir/'log'}"
        logger.info('run command: ' + command)
        os.system(command)
        logger.info('gamma command finished.')
        dat = pd.read_csv(bperp, sep='\s+', header=None)
        base=dat[3].to_numpy()
        base=base.astype(np.float32)

    meta['perpendicular_baseline'] = base

    with open(meta_file,'w') as f:
        a = toml.dump(meta,f,encoder=toml.TomlNumpyEncoder())
    logger.info('All meta data: \n'+a)
    logger.info('writing data in toml file.')
    logger.info('Done.')
