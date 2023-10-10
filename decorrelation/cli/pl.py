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
from dask.distributed import Client, LocalCluster
from dask_cuda import LocalCUDACluster

from ..pl import emi
from ..pc import pc2ras
from .utils.logging import get_logger, log_args
# from decorrelation.cli.utils.dask import pad_internal

from fastcore.script import call_parse

# %% ../../nbs/CLI/pl.ipynb 5
@call_parse
@log_args
def de_emi(coh:str, # coherence matrix
           ph:str, # output, wrapped phase
           emi_quality:str, #output, pixel quality
           ref:int=0, # reference image for phase
           point_chunk_size:int=None, # parallel processing point chunk size
           log:str=None, #log
           plot_emi_quality:bool=False, # if plot the emi quality
           vmin:int=1.0, # min value of emi quality to plot
           vmax:int=1.3, # max value of emi quality to plot
           ds_idx:str=None, # index of ds
           shape:tuple=None, # shape of one image
           emi_quality_fig:str=None, # path to save the emi quality plot, optional. Default, no saving
          ):
    coh_path = coh
    ph_path = ph
    emi_quality_path = emi_quality
    ds_idx_path = ds_idx

    logger = get_logger(logfile=log)
    coh_zarr = zarr.open(coh_path,mode='r')
    logger.info('coh dataset shape: '+str(coh_zarr.shape))
    logger.info('coh dataset chunks: '+str(coh_zarr.chunks))

    if not point_chunk_size:
        point_chunk_size = coh_zarr.chunks[0]
        logger.info('using default parallel processing azimuth chunk size from coh dataset.')
    logger.info('parallel processing point chunk size: '+str(point_chunk_size))

    logger.info('starting dask CUDA local cluster.')
    cluster = LocalCUDACluster()
    client = Client(cluster)
    logger.info('dask local CUDA cluster started.')

    cpu_coh = da.from_zarr(coh_path, chunks=(point_chunk_size,*coh_zarr.shape[1:]))
    logger.info('coh dask array shape: ' + str(cpu_coh.shape))
    logger.info('coh dask array chunks: '+ str(cpu_coh.chunks))

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
    logger.info('ph dask array shape: ' + str(cpu_ph.shape))
    logger.info('ph dask array chunks: '+ str(cpu_ph.chunks))
    logger.info('emi_quality dask array shape: ' + str(cpu_emi_quality.shape))
    logger.info('emi_quality dask array chunks: '+ str(cpu_emi_quality.chunks))

    logger.info('saving ph and emi_quality.')
    _cpu_ph = cpu_ph.to_zarr(ph_path,compute=False,overwrite=True)
    _cpu_emi_quality = cpu_emi_quality.to_zarr(emi_quality_path,compute=False,overwrite=True)
    
    if not plot_emi_quality:
        logger.info('computing graph setted. doing all the computing.')
        da.compute(_cpu_ph,_cpu_emi_quality)
        logger.info('computing finished.')
        cluster.close()
        logger.info('dask cluster closed.')
    else:
        logger.info('computing graph setted. doing all the computing.')
        emi_quality_result = da.compute(cpu_emi_quality,_cpu_ph,_cpu_emi_quality)[0]
        logger.info('computing finished.')
        cluster.close()
        logger.info('dask cluster closed.')

        logger.info('plotting emi_quality.')
        logger.info('reading is_ds bool array')
        ds_idx_result = zarr.open(ds_idx_path,mode='r')[:]

        emi_quality_raster = pc2ras(ds_idx_result,emi_quality_result,shape)
        logger.info('converting emi_quality from point cloud to raster.')
        fig, ax = plt.subplots(1,1)
        pcm = ax.imshow(emi_quality_raster,interpolation='nearest',vmin=vmin,vmax=vmax)
        ax.set(title='EMI quality factor',xlabel='Range Index',ylabel='Azimuth Index')
        fig.colorbar(pcm)
        if emi_quality_fig:
            logger.info('saving figure')
            fig.savefig(emi_quality_fig)
        logger.info('showing')
        fig.show()
