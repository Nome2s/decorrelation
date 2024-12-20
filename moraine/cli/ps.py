# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/ps.ipynb.

# %% auto 0
__all__ = ['amp_disp']

# %% ../../nbs/CLI/ps.ipynb 4
import logging
import zarr
import time
import numpy as np

import dask
from dask import array as da
from dask import delayed
from dask.distributed import Client, LocalCluster, progress
from ..utils_ import is_cuda_available, get_array_module
if is_cuda_available():
    import cupy as cp
    from dask_cuda import LocalCUDACluster
    from rmm.allocators.cupy import rmm_cupy_allocator
import moraine as mr
from .logging import mc_logger
from . import dask_from_zarr, dask_to_zarr

# %% ../../nbs/CLI/ps.ipynb 5
@mc_logger
def amp_disp(
    rslc:str, # rslc stack
    adi:str, #output, amplitude dispersion index
    chunks:tuple[int,int]=None, # data processing chunk size, same as rslc by default
    out_chunks:tuple[int,int]=None, # output data chunk size, same as chunks by default
    cuda:bool=False, # if use cuda for processing, false by default
    processes=None, # use process for dask worker over thread, the default is False for cpu, only applied if cuda==False
    n_workers=None, # number of dask worker, the default is 1 for cpu, number of GPU for cuda
    threads_per_worker=None, # number of threads per dask worker, the default is 1 for cpu, only applied if cuda==False
    rmm_pool_size=0.9, # set the rmm pool size, only applied when cuda==True
    **dask_cluster_arg, # other dask local/cudalocal cluster args
):
    '''calculation the amplitude dispersion index from SLC stack.'''
    rslc_path = rslc
    adi_path = adi
    logger = logging.getLogger(__name__)
    rslc_zarr = zarr.open(rslc_path,mode='r')
    logger.zarr_info(rslc_path,rslc_zarr)
    if chunks is None: chunks = rslc_zarr.chunks[:2]
    if out_chunks is None: out_chunks = chunks
    if cuda:
        Cluster = LocalCUDACluster; cluster_args= {
            'n_workers':n_workers,
            'rmm_pool_size':rmm_pool_size}
        cluster_args.update(dask_cluster_arg)
        xp = cp
    else:
        if processes is None: processes = False
        if n_workers is None: n_workers = 1
        if threads_per_worker is None: threads_per_worker = 1
        Cluster = LocalCluster; cluster_args = {'processes':processes, 'n_workers':n_workers, 'threads_per_worker':threads_per_worker}
        cluster_args.update(dask_cluster_arg)
        xp = np

    logger.info('starting dask local cluster.')
    with Cluster(**cluster_args) as cluster, Client(cluster) as client:
        if cuda:
            client.run(cp.cuda.set_allocator, rmm_cupy_allocator)
        logger.info('dask local cluster started.')
        logger.dask_cluster_info(cluster)

        cpu_rslc = dask_from_zarr(rslc_path,chunks=(*chunks,*rslc_zarr.shape[2:]))
        logger.darr_info('rslc', cpu_rslc)
        logger.info(f'calculate amplitude dispersion index.')
        rslc = cpu_rslc.map_blocks(cp.asarray) if cuda else cpu_rslc
        rslc_delayed = rslc.to_delayed()
        adi_delayed = np.empty_like(rslc_delayed,dtype=object)
        with np.nditer(rslc_delayed,flags=['multi_index','refs_ok'], op_flags=['readwrite']) as it:
            for block in it:
                idx = it.multi_index
                adi_delayed[idx] = delayed(mr.amp_disp,pure=True,nout=1)(rslc_delayed[idx])
                adi_delayed[idx] =da.from_delayed(adi_delayed[idx],shape=rslc.blocks[idx].shape[0:2],meta=xp.array((),dtype=xp.float32))
        adi = da.block(adi_delayed[...,0].tolist())
        
        logger.info(f'got amplitude dispersion index.')
        logger.darr_info('adi', adi)

        cpu_adi = adi.map_blocks(cp.asnumpy) if cuda else adi
        logger.darr_info('adi', cpu_adi)
        logger.info('saving adi.')
        _adi = dask_to_zarr(cpu_adi,adi_path,chunks=out_chunks)
        # _adi = da.to_zarr(cpu_adi,adi_path,compute=False,overwrite=True)

        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist(_adi)
        progress(futures,notebook=False)
        time.sleep(0.1)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')
