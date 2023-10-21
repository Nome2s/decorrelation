# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/pl.ipynb.

# %% auto 0
__all__ = ['de_emi']

# %% ../../nbs/CLI/pl.ipynb 4
import math

import zarr
import cupy as cp
import numpy as np
from matplotlib import pyplot as plt
import colorcet

import dask
from dask import array as da
from dask import delayed
from dask.distributed import Client, LocalCluster, progress
from dask_cuda import LocalCUDACluster

from ..pl import emi
from .pc import de_pc2ras
from .utils.logging import get_logger, log_args
from .utils.chunk_size import get_pc_chunk_size_from_pc_chunk_size
from .utils.dask import get_cuda_cluster_arg

from fastcore.script import call_parse

# %% ../../nbs/CLI/pl.ipynb 5
@call_parse
@log_args
def de_emi(coh:str, # coherence matrix
           ph:str, # output, wrapped phase
           emi_quality:str, #output, pixel quality
           ref:int=0, # reference image for phase
           n_pc_chunk:int=None, # number of point cloud chunk
           pc_chunk_size:int=None, # point cloud chunk size
           log:str=None, #log
          ):
    '''Phase linking with EMI estimator.
    '''
    coh_path = coh
    ph_path = ph
    emi_quality_path = emi_quality

    logger = get_logger(logfile=log)
    coh_zarr = zarr.open(coh_path,mode='r')
    logger.zarr_info(coh_path,coh_zarr)

    pc_chunk_size = get_pc_chunk_size_from_pc_chunk_size('coh','ph',coh_zarr.chunks[0],coh_zarr.shape[0],logger,n_pc_chunk=n_pc_chunk,pc_chunk_size=pc_chunk_size)

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

        logger.info('saving ph and emi_quality.')
        _cpu_ph = cpu_ph.to_zarr(ph_path,compute=False,overwrite=True)
        _cpu_emi_quality = cpu_emi_quality.to_zarr(emi_quality_path,compute=False,overwrite=True)

        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist([_cpu_ph,_cpu_emi_quality])
        progress(futures,notebook=False)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')
