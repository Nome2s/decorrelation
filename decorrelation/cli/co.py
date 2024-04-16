# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/co.ipynb.

# %% auto 0
__all__ = ['mean_coh_kernel', 'mean_coh_pc', 'de_emperical_co_pc']

# %% ../../nbs/CLI/co.ipynb 4
import logging

import zarr
import numpy as np

import dask
from dask import array as da
from dask import delayed
from dask.distributed import Client, LocalCluster, progress
try:
    import cupy as cp
    from dask_cuda import LocalCUDACluster
except ImportError:
    pass

from ..co import emperical_co_pc
from .utils.logging import de_logger, log_args
from .utils.dask import pad_internal, get_cuda_cluster_arg
from .utils.chunk_size import get_pc_chunk_size_from_pc_chunk_size

from fastcore.script import call_parse

# %% ../../nbs/CLI/co.ipynb 5
mean_coh_kernel = cp.ReductionKernel(
    'T x, raw int32 n_point',  # input params
    'float32 y',  # output params
    'abs(x)',  # map
    'a + b',  # reduce
    'y = a/n_point',  # post-reduction map
    '0',  # identity value
    'mean_coh'  # kernel name
)

# %% ../../nbs/CLI/co.ipynb 6
def mean_coh_pc(coh):
    return mean_coh_kernel(coh,cp.int32(coh.shape[0]),axis=0)

# %% ../../nbs/CLI/co.ipynb 8
@call_parse
@log_args
def de_emperical_co_pc(rslc:str, # input: rslc stack
                       is_shp:str, # input: bool array indicating the SHPs of pc
                       gix:str, # input: bool array indicating pc
                       coh:str, # output: complex coherence matrix for pc
                       coh_ave:str, # output: average value of coherence matrix magnitude
                       az_chunk_size:int=None, # processing azimuth chunk size, optional. Default: the azimuth chunk size in rslc stack
                       n_pc_chunk:int=None, # number of point chunk, optional.
                       pc_chunk_size:int=None, # chunk size of output zarr dataset, optional. Default: same as is_shp
                       ):
    '''estimate emperical coherence matrix on point cloud data.
    Due to the data locality problem. r_chunk_size for the processing have to be one.
    Only one of `n_pc_chunk` and `pc_chunk_size` needs to be setted. The other one is automatically determined.
    If all of them are not setted, the `n_pc_chunk` will be setted as the number of azimuth chunks.
    '''
    rslc_path = rslc
    is_shp_path = is_shp
    gix_path = gix
    coh_path = coh
    coh_ave_path = coh_ave
    logger = logging.getLogger(__name__)

    rslc_zarr = zarr.open(rslc_path,mode='r')
    logger.zarr_info(rslc_path, rslc_zarr)
    assert rslc_zarr.ndim == 3, "rslc dimentation is not 3."
    nlines, width, nimage = rslc_zarr.shape

    is_shp_zarr = zarr.open(is_shp_path,mode='r')
    logger.zarr_info(is_shp_path, is_shp_zarr)
    assert is_shp_zarr.ndim == 3, "is_shp dimentation is not 3."

    gix_zarr = zarr.open(gix_path,mode='r')
    logger.zarr_info(gix_path, gix_zarr)
    assert gix_zarr.ndim == 2, "gix dimentation is not 2."
    logger.info('loading gix into memory.')
    gix = zarr.open(gix_path,mode='r')[:]

    az_win, r_win = is_shp_zarr.shape[1:]
    az_half_win = int((az_win-1)/2)
    r_half_win = int((r_win-1)/2)
    logger.info(f'''got azimuth window size and half azimuth window size
    from is_shp shape: {az_win}, {az_half_win}''')
    logger.info(f'''got range window size and half range window size
    from is_shp shape: {r_win}, {r_half_win}''')

    if az_chunk_size is None: az_chunk_size = rslc_zarr.chunks[0]
    logger.info('parallel processing azimuth chunk size: '+str(az_chunk_size))
    logger.info('parallel processing range chunk size: 1.')

    n_az_chunk = int(np.ceil(nlines/az_chunk_size))
    j_chunk_boundary = np.arange(n_az_chunk+1)*1000; j_chunk_boundary[-1] = nlines
    point_boundary = np.searchsorted(gix[0],j_chunk_boundary)
    process_pc_chunk_size = np.diff(point_boundary)
    process_pc_chunk_size = tuple(process_pc_chunk_size.tolist())
    logger.info(f'number of point in each chunk: {process_pc_chunk_size}')
    
    logger.info('starting dask CUDA local cluster.')
    with LocalCUDACluster(**get_cuda_cluster_arg()) as cluster, Client(cluster) as client:
        logger.info('dask local CUDA cluster started.')
        emperical_co_pc_delayed = delayed(emperical_co_pc,pure=True,nout=2)

        cpu_is_shp = da.from_zarr(is_shp_path,chunks=(process_pc_chunk_size,(az_win,),(r_win,)))
        logger.darr_info('is_shp', cpu_is_shp)
        is_shp = cpu_is_shp.map_blocks(cp.asarray)
        is_shp_delayed = is_shp.to_delayed()
        is_shp_delayed = np.squeeze(is_shp_delayed,axis=(-2,-1))

        cpu_rslc = da.from_zarr(rslc_path,chunks=(az_chunk_size,*rslc_zarr.shape[1:]))
        logger.darr_info('rslc', cpu_rslc)
        depth = {0:az_half_win, 1:r_half_win, 2:0}; boundary = {0:'none',1:'none',2:'none'}
        cpu_rslc_overlap = da.overlap.overlap(cpu_rslc,depth=depth, boundary=boundary)
        logger.info('setting shared boundaries between rlsc chunks.')
        logger.darr_info('rslc_overlap', cpu_rslc_overlap)
        rslc_overlap = cpu_rslc_overlap.map_blocks(cp.asarray)
        rslc_overlap_delayed = np.squeeze(rslc_overlap.to_delayed(),axis=(-2,-1))

        coh_delayed = np.empty_like(is_shp_delayed,dtype=object)
        coh_ave_delayed = np.empty_like(is_shp_delayed,dtype=object)

        logger.info(f'estimating coherence matrix.')
        for j in range(n_az_chunk):
            jstart = j*az_chunk_size; jend = jstart + az_chunk_size
            if jend>=nlines: jend = nlines
            gix_local_j = gix[0,point_boundary[j]:point_boundary[j+1]]-jstart
            if j!= 0: gix_local_j += az_half_win
            gix_local_i = gix[1,point_boundary[j]:point_boundary[j+1]]
            gix_local = np.stack((gix_local_j,gix_local_i))
            gix_local_delayed = da.from_array(gix_local).map_blocks(cp.asarray)

            coh_delayed[j] = emperical_co_pc_delayed(rslc_overlap_delayed[j],gix_local_delayed,is_shp_delayed[j])[1]
            coh_ave_delayed[j] = delayed(mean_coh_pc)(coh_delayed[j])
            coh_delayed[j] = da.from_delayed(coh_delayed[j],shape=(process_pc_chunk_size[j],nimage,nimage),meta=cp.array((),dtype=cp.complex64))
            coh_ave_delayed[j] = (da.from_delayed(coh_ave_delayed[j],shape=(nimage,nimage),meta=cp.array((),dtype=cp.float32))).reshape(1,nimage,nimage)

        coh = da.block(coh_delayed[...,None,None].tolist())
        cpu_coh = coh.map_blocks(cp.asnumpy)
        coh_ave = da.block(coh_ave_delayed[...,None,None].tolist())
        logger.info('get coherence matrix.'); logger.darr_info('coh', cpu_coh)

        pc_chunk_size = get_pc_chunk_size_from_pc_chunk_size('is_pc','coh',
                                                             is_shp_zarr.chunks[0],
                                                             cpu_coh.shape[0],
                                                             pc_chunk_size=pc_chunk_size,n_pc_chunk=n_pc_chunk)
        cpu_coh = cpu_coh.rechunk((pc_chunk_size,1,1))
        logger.info('rechunking coh to chunk size (for saving with zarr): '+str(cpu_coh.chunksize))
        logger.darr_info('coh', cpu_coh)

        cpu_coh_ave = coh_ave.map_blocks(cp.asnumpy)
        cpu_coh_ave = cpu_coh_ave.mean(axis=0)
        logger.info('get average coherence matrix magnitude.')
        logger.darr_info('coh_ave', cpu_coh_ave)

        logger.info('saving coh and coh_ave.')
        _cpu_coh = cpu_coh.to_zarr(coh_path,overwrite=True,compute=False)
        _cpu_coh_ave = cpu_coh_ave.to_zarr(coh_ave_path,overwrite=True,compute=False)

        logger.info('computing graph setted. doing all the computing.')
        #This function is really slow just because the coherence is very big and rechunk and saving takes too much time.
        # I do not find any solution to it.
        futures = client.persist([_cpu_coh,_cpu_coh_ave])
        progress(futures,notebook=False)
        da.compute(futures)
        # pdb.set_trace()
        logger.info('computing finished.')
    logger.info('dask cluster closed.')
