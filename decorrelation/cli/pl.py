# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/pl.ipynb.

# %% auto 0
__all__ = ['de_emi', 'de_ds_temp_coh']

# %% ../../nbs/CLI/pl.ipynb 5
import logging

import zarr
import cupy as cp
import numpy as np

import dask
from dask import array as da
from dask import delayed
from dask.distributed import Client, LocalCluster, progress
from dask_cuda import LocalCUDACluster

from ..pl import emi, ds_temp_coh
from .utils.logging import de_logger, log_args
from .utils.chunk_size import get_pc_chunk_size_from_pc_chunk_size
from .utils.dask import get_cuda_cluster_arg

from fastcore.script import call_parse

# %% ../../nbs/CLI/pl.ipynb 6
@call_parse
@log_args
@de_logger
def de_emi(coh:str, # coherence matrix
           ph:str, # output, wrapped phase
           emi_quality:str, #output, pixel quality
           ref:int=0, # reference image for phase
           n_pc_chunk:int=None, # number of point cloud chunk
           pc_chunk_size:int=None, # point cloud chunk size
          ):
    '''Phase linking with EMI estimator.
    '''
    coh_path = coh
    ph_path = ph
    emi_quality_path = emi_quality

    logger = logging.getLogger(__name__)
    coh_zarr = zarr.open(coh_path,mode='r')
    logger.zarr_info(coh_path,coh_zarr)

    pc_chunk_size = get_pc_chunk_size_from_pc_chunk_size('coh','ph',coh_zarr.chunks[0],coh_zarr.shape[0],n_pc_chunk=n_pc_chunk,pc_chunk_size=pc_chunk_size)

    logger.info('starting dask CUDA local cluster.')
    with LocalCUDACluster(CUDA_VISIBLE_DEVICES=get_cuda_cluster_arg()['CUDA_VISIBLE_DEVICES']) as cluster, Client(cluster) as client:
        logger.info('dask local CUDA cluster started.')

        cpu_coh = da.from_zarr(coh_path, chunks=(pc_chunk_size,*coh_zarr.shape[1:]))
        logger.darr_info('coh', cpu_coh)

        logger.info(f'phase linking with EMI.')
        coh = cpu_coh.map_blocks(cp.asarray)
        coh_delayed = coh.to_delayed()
        coh_delayed = np.squeeze(coh_delayed,axis=(-2,-1))

        ph_delayed = np.empty_like(coh_delayed,dtype=object)
        emi_quality_delayed = np.empty_like(coh_delayed,dtype=object)

        with np.nditer(coh_delayed,flags=['multi_index','refs_ok'], op_flags=['readwrite']) as it:
            for block in it:
                idx = it.multi_index
                ph_delayed[idx], emi_quality_delayed[idx] = delayed(emi,pure=True,nout=2)(coh_delayed[idx])
                ph_delayed[idx] = da.from_delayed(ph_delayed[idx],shape=coh.blocks[idx].shape[0:2],meta=cp.array((),dtype=coh.dtype))
                emi_quality_delayed[idx] = da.from_delayed(emi_quality_delayed[idx],shape=coh.blocks[idx].shape[0:1],meta=cp.array((),dtype=cp.float32))

        ph = da.block(ph_delayed[...,None].tolist())
        emi_quality = da.block(emi_quality_delayed.tolist())

        cpu_ph = ph.map_blocks(cp.asnumpy)
        cpu_emi_quality = emi_quality.map_blocks(cp.asnumpy)
        logger.info(f'got ph and emi_quality.')
        logger.darr_info('ph', cpu_ph)
        logger.darr_info('emi_quality', cpu_emi_quality)

        logger.info(f'rechunk ph')
        cpu_ph.rechunk((cpu_ph.chunksize[0],1,1))
        logger.darr_info('ph', cpu_ph)

        logger.info('saving ph and emi_quality.')
        _cpu_ph = cpu_ph.to_zarr(ph_path,compute=False,overwrite=True)
        _cpu_emi_quality = cpu_emi_quality.to_zarr(emi_quality_path,compute=False,overwrite=True)

        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist([_cpu_ph,_cpu_emi_quality])
        progress(futures,notebook=False)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')

# %% ../../nbs/CLI/pl.ipynb 12
@call_parse
@log_args
@de_logger
def de_ds_temp_coh(coh:str, # coherence matrix
                   ph:str, # wrapped phase
                   t_coh:str, # output, temporal coherence
                   n_pc_chunk:int=None, # number of point cloud chunk
                   pc_chunk_size:int=None, # point cloud chunk size
                  ):
    '''DS temporal coherence.
    '''
    coh_path = coh
    ph_path = ph
    t_coh_path = t_coh

    logger = logging.getLogger(__name__)
    coh_zarr = zarr.open(coh_path,mode='r'); logger.zarr_info(coh_path,coh_zarr)
    ph_zarr = zarr.open(ph_path,mode='r'); logger.zarr_info(ph_path,ph_zarr)

    pc_chunk_size = get_pc_chunk_size_from_pc_chunk_size('coh','ph',coh_zarr.chunks[0],coh_zarr.shape[0],n_pc_chunk=n_pc_chunk,pc_chunk_size=pc_chunk_size)

    logger.info('starting dask CUDA local cluster.')
    with LocalCUDACluster(CUDA_VISIBLE_DEVICES=get_cuda_cluster_arg()['CUDA_VISIBLE_DEVICES']) as cluster, Client(cluster) as client:
        logger.info('dask local CUDA cluster started.')

        cpu_coh = da.from_zarr(coh_path, chunks=(pc_chunk_size,*coh_zarr.shape[1:]))
        logger.darr_info('coh', cpu_coh)
        
        cpu_ph = da.from_zarr(ph_path, chunks=(pc_chunk_size,*ph_zarr.shape[1:]))
        logger.darr_info('ph', cpu_ph)

        logger.info(f'Estimate temporal coherence for DS.')
        coh = cpu_coh.map_blocks(cp.asarray)
        ph = cpu_ph.map_blocks(cp.asarray)

        coh_delayed = coh.to_delayed()
        coh_delayed = np.squeeze(coh_delayed,axis=(-2,-1))
        ph_delayed = ph.to_delayed()
        ph_delayed = np.squeeze(ph_delayed,axis=-1)
        t_coh_delayed = np.empty_like(coh_delayed,dtype=object)

        with np.nditer(coh_delayed,flags=['multi_index','refs_ok'], op_flags=['readwrite']) as it:
            for block in it:
                idx = it.multi_index
                t_coh_delayed[idx] = delayed(ds_temp_coh,pure=True,nout=1)(coh_delayed[idx],ph_delayed[idx])
                t_coh_delayed[idx] = da.from_delayed(t_coh_delayed[idx],shape=coh.blocks[idx].shape[0:1],meta=cp.array((),dtype=cp.float32))

            t_coh = da.block(t_coh_delayed.tolist())
    
        cpu_t_coh = t_coh.map_blocks(cp.asnumpy)
        logger.info(f'got temporal coherence t_coh.')
        logger.darr_info('t_coh', t_coh)

        logger.info('saving t_coh.')
        _cpu_t_coh = cpu_t_coh.to_zarr(t_coh_path,compute=False,overwrite=True)

        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist(_cpu_t_coh)
        progress(futures,notebook=False)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')
