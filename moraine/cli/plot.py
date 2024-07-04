# AUTOGENERATED! DO NOT EDIT! File to edit: ../../nbs/CLI/plot.ipynb.

# %% auto 0
__all__ = ['ras_pyramid', 'ras_plot', 'pc_pyramid', 'pc_plot']

# %% ../../nbs/CLI/plot.ipynb 4
import logging
import zarr
import numpy as np
import math
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import sys
from functools import partial
from typing import Callable
import numpy as np
from numba import prange
import holoviews as hv
from holoviews import streams

import dask
from dask import array as da
from dask import delayed
from dask.distributed import Client, LocalCluster, progress
import time

import toml
from ..utils_ import ngpjit
from ..rtree import HilbertRtree
from .logging import mc_logger
from ..coord_ import Coord

# %% ../../nbs/CLI/plot.ipynb 5
def _zarr_stack_info(
    zarr_path_list, #list of zarr path
):
    shape_list = []; chunks_list = []; dtype_list = []
    for zarr_path in zarr_path_list:
        zarr_data = zarr.open(zarr_path,'r')
        shape_list.append(zarr_data.shape)
        chunks_list.append(zarr_data.chunks)
        dtype_list.append(zarr_data.dtype)
    df = pd.DataFrame({'path':zarr_path_list,'shape':shape_list,'chunks':chunks_list,'dtype':dtype_list})
    return df

# %% ../../nbs/CLI/plot.ipynb 7
def _ras_downsample(ras,down_level=1):
    return ras[::2**down_level,::2**down_level]

# %% ../../nbs/CLI/plot.ipynb 8
@mc_logger
def ras_pyramid(
    ras:str, # path to input data, 2D zarr array (one single raster) or 3D zarr array (a stack of rasters)
    out_dir:str, # output directory to store rendered data
    chunks:tuple[int,int]=(256,256), # output raster tile size
    processes=False, # use process for dask worker over thread
    n_workers=1, # number of dask worker
    threads_per_worker=2, # number of threads per dask worker
    **dask_cluster_arg, # other dask local cluster args
):
    '''render raster data to pyramid of difference zoom levels.'''
    logger = logging.getLogger(__name__)
    out_dir = Path(out_dir); out_dir.mkdir(exist_ok=True)
    ras_zarr = zarr.open(ras,'r')
    logger.zarr_info(ras, ras_zarr)
    
    ny, nx = ras_zarr.shape[0:2]
    n_channel = ras_zarr.ndim-2
    out_chunks = chunks
    channel_chunks = ((1,)*n_channel)
    maxlevel = math.floor(math.log2(min(nx,ny))) # so at least 2 pixels
    
    logger.info(f'rendered raster pyramid with zoom level ranging from 0 (finest resolution) to {maxlevel} (coarsest resolution).')

    with LocalCluster(processes=processes,
                      n_workers=n_workers,
                      threads_per_worker=threads_per_worker,
                      **dask_cluster_arg) as cluster, Client(cluster) as client:
        logger.info('dask local cluster started.')
        logger.dask_cluster_info(cluster)
        ras_data = da.from_zarr(ras,chunks=(ny,nx,*channel_chunks))
        output_futures = []
        for level in range(maxlevel+1):
            if level == 0: # no downsampling, just copy
                downsampled_ras = ras_data.map_blocks(_ras_downsample,down_level=0,dtype=ras_data.dtype,chunks=ras_data.chunks)
            else:
                chunks = (math.ceil(ny/(2**level)), math.ceil(nx/(2**level)), *channel_chunks)
                downsampled_ras = last_downsampled_ras.map_blocks(_ras_downsample,dtype=ras_data.dtype,chunks=chunks)
            last_downsampled_ras = downsampled_ras
            out_downsampled_ras = downsampled_ras.rechunk((*out_chunks,*channel_chunks))
            logger.darr_info(f'downsampled ras in level {level}',out_downsampled_ras)
            output_future = da.to_zarr(out_downsampled_ras, zarr.NestedDirectoryStore(out_dir/f'{level}.zarr'), compute=False,overwrite=True)
            output_futures.append(output_future)
            # output_futures.append(downsampled_ras.rechunk((*out_chunks,*channel_chunks)).to_zarr(zarr.NestedDirectoryStore(out_dir/f'{level}.zarr')))
        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist(output_futures)
        progress(futures,notebook=False)
        time.sleep(0.1)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')

# %% ../../nbs/CLI/plot.ipynb 14
# there should be better way to achieve variable kdims, but I don't find that.
def _hv_ras_callback_0(x_range,y_range,width,height,scale,data_dir,post_proc,coord,level_increase):
    # start = time.time()
    if x_range is None:
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if y_range is None:
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res,y_res)))
    level += level_increase
    level = sorted((0, level, coord.maxlevel))[1]
    data_zarr = zarr.open(data_dir/f'{level}.zarr','r')
    xi0, yi0, xim, yim = coord.hv_bbox2gix_bbox((x0,y0,xm,ym),level)
    coord_bbox = coord.gix_bbox2hv_bbox((xi0, yi0, xim, yim),level)
    # decide_slice = time.time()
    data = post_proc(data_zarr,slice(xi0,xim+1),slice(yi0,yim+1))
    # post_proc_data = time.time()
    # print(f"It takes {post_proc_data-decide_slice} to post_proc the data", file = sourceFile)
    ### test shows data read takes only 0.006 s, post_proc and data_range takes only 0.001s
    ### the majority of time is used by holoviews that I can not optimize.
    return hv.Image(data[::-1,:],bounds=coord_bbox)
def _hv_ras_callback_1(x_range,y_range,width,height,scale,data_dir,post_proc,coord,level_increase,i=0):
    if x_range is None:
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if y_range is None:
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res,y_res)))
    level = sorted((0, level, coord.maxlevel))[1]
    level += level_increase
    data_zarr = zarr.open(data_dir/f'{level}.zarr','r')
    xi0, yi0, xim, yim = coord.hv_bbox2gix_bbox((x0,y0,xm,ym),level)
    coord_bbox = coord.gix_bbox2hv_bbox((xi0, yi0, xim, yim),level)
    data = post_proc(data_zarr,slice(xi0,xim+1),slice(yi0,yim+1),i)
    return hv.Image(data[::-1,:],bounds=coord_bbox)
def _hv_ras_callback_2(x_range,y_range,width,height,scale,data_dir,post_proc,coord,level_increase,i=0,j=0):
    if x_range is None:
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if y_range is None:
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res,y_res)))
    level = sorted((0, level, coord.maxlevel))[1]
    level += level_increase
    data_zarr = zarr.open(data_dir/f'{level}.zarr','r')
    xi0, yi0, xim, yim = coord.hv_bbox2gix_bbox((x0,y0,xm,ym),level)
    coord_bbox = coord.gix_bbox2hv_bbox((xi0, yi0, xim, yim),level)
    data = post_proc(data_zarr,slice(xi0,xim+1),slice(yi0,yim+1),i,j)
    return hv.Image(data[::-1,:],bounds=coord_bbox)

# %% ../../nbs/CLI/plot.ipynb 15
def _default_ras_post_proc(data_zarr, xslice, yslice, *kdims):
    data_n_kdim = data_zarr.ndim - 2
    assert len(kdims) == data_n_kdim
    if len(kdims) == 0:
        # zarr do not support empty tuple as input
        return data_zarr[yslice,xslice]
    else:
        return data_zarr[yslice,xslice,kdims]

# %% ../../nbs/CLI/plot.ipynb 16
def _ras_inf_0_post_proc(data_zarr, xslice, yslice, *kdims):
    data_n_kdim = data_zarr.ndim - 2
    assert len(kdims) == 1
    i = kdims[0]
    if data_n_kdim == 1:
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[yslice,xslice,i]*data_zarr[yslice,xslice,0].conj())
        else:
            return data_zarr[yslice,xslice,i]-data_zarr[yslice,xslice,0]
    else:
        assert data_n_kdim == 2
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[yslice,xslice,i,0])
        else:
            return data_zarr[yslice,xslice,i,0]

def _ras_inf_seq_post_proc(data_zarr, xslice, yslice, *kdims):
    data_n_kdim = data_zarr.ndim - 2
    assert len(kdims) == 1
    i = kdims[0]
    if data_n_kdim == 1:
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[yslice,xslice,i]*data_zarr[yslice,xslice,i-1].conj())
        else:
            return data_zarr[yslice,xslice,i]-data_zarr[yslice,xslice,i-1]
    else:
        assert data_n_kdim == 2
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[yslice,xslice,i,i-1])
        else:
            return data_zarr[yslice,xslice,i,i-1]
def _ras_inf_all_post_proc(data_zarr, xslice, yslice, *kdims):
    data_n_kdim = data_zarr.ndim - 2
    assert len(kdims) == 2
    i,j = kdims
    if data_n_kdim == 1:
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[yslice,xslice,i]*data_zarr[yslice,xslice,j].conj())
        else:
            return data_zarr[yslice,xslice,i]-data_zarr[yslice,xslice,j]
    else:
        assert data_n_kdim == 2
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[yslice,xslice,i,j])
        else:
            return data_zarr[yslice,xslice,i,j]

# %% ../../nbs/CLI/plot.ipynb 17
def ras_plot(
    pyramid_dir:str, # directory to the rendered ras pyramid
    post_proc:Callable=None, # function for the post processing, can be None, 'intf_0', 'intf_seq', 'intf_all' or user-defined function
    n_kdim:int=None, # number of key dimensions, can only be 0 or 1 or 2, ndim of raster dataset -2 by default
    bounds:tuple=None, # bounding box (x0, y0, x_max, y_max)
    level_increase=0, # amount of zoom level increase for more clear point show and faster responds time
):
    '''plot rendered stack of ras tiles.'''
    pyramid_dir = Path(pyramid_dir)
    data_zarr = zarr.open(pyramid_dir/'0.zarr','r')
    ny, nx = data_zarr.shape[:2]
    if post_proc is None: 
        post_proc = _default_ras_post_proc
    elif post_proc == 'intf_0':
        post_proc = _ras_inf_0_post_proc
        n_kdim = 1
    elif post_proc == 'intf_seq':
        post_proc = _ras_inf_seq_post_proc
        n_kdim = 1
    elif post_proc == 'intf_all':
        post_proc = _ras_inf_all_post_proc
        n_kdim = 2

    if n_kdim is None: n_kdim = data_zarr.ndim -2 
    assert n_kdim <= 2, 'n_kdim can only be 0 or 1 or2.'
    kdims = ['i','j'][:n_kdim]

    if len(kdims) == 0:
        hv_ras_callback = _hv_ras_callback_0
    elif len(kdims) == 1:
        hv_ras_callback = _hv_ras_callback_1
    elif len(kdims) == 2:
        hv_ras_callback = _hv_ras_callback_2

    if bounds is None:
        x0 = 0; dx = 1; y0 = 0; dy = 1
    else:
        x0, y0, xm, ym = bounds
        dx = (xm-x0)/(nx-1); dy = (ym-y0)/(ny-1)
    coord = Coord(x0,dx,nx,y0,dy,ny)

    rangexy = streams.RangeXY()
    plotsize = streams.PlotSize()
    images = hv.DynamicMap(partial(hv_ras_callback,data_dir=pyramid_dir,
                                   post_proc=post_proc,coord=coord,level_increase=level_increase),streams=[rangexy,plotsize],kdims=kdims)
    return images

# %% ../../nbs/CLI/plot.ipynb 51
@ngpjit
def _next_level_idx_from_raster_of_integer(pc_idx, nan_value):
    '''return the raster indices to the next level of raster'''
    assert pc_idx.ndim == 2
    ny, nx = pc_idx.shape
    next_ny, next_nx = math.ceil(ny/2), math.ceil(nx/2)
    xi = np.empty((next_ny,next_nx), dtype=np.int32)
    yi = np.empty((next_ny,next_nx), dtype=np.int32)

    for i in range(next_ny):
        for j in prange(next_nx):
            # Select a 2x2 box from the original array
            box = pc_idx[i*2:min(i*2+2, ny), j*2:min(j*2+2, nx)]
            idx_ = np.argwhere(box != nan_value)
            if len(idx_) == 0:
                yi[i,j]= i*2
                xi[i,j] = j*2
            else:
                yi[i,j] = idx_[0,0] + i*2
                xi[i,j] = idx_[0,1] + j*2
    return yi, xi

# %% ../../nbs/CLI/plot.ipynb 52
# currently not used
@ngpjit
def _next_level_idx_from_raster_of_noninteger(pc_data):
    '''return the raster indices to the next level of raster'''
    assert pc_data.ndim == 2
    ny, nx = pc_data.shape
    next_ny, next_nx = math.ceil(ny/2), math.ceil(nx/2)
    xi = np.empty((next_ny,next_nx), dtype=np.int32)
    yi = np.empty((next_ny,next_nx), dtype=np.int32)

    for i in range(next_ny):
        for j in prange(next_nx):
            # Select a 2x2 box from the original array
            box = pc_data[i*2:min(i*2+2, ny), j*2:min(j*2+2, nx)]
            idx_ = np.argwhere(~np.isnan(box))
            if len(idx_) == 0:
                yi[i,j]= i*2
                xi[i,j] = j*2
            else:
                yi[i,j] = idx_[0,0] + i*2
                xi[i,j] = idx_[0,1] + j*2
    return yi, xi

# %% ../../nbs/CLI/plot.ipynb 54
def _next_ras(ras,yi,xi):
    return ras[yi,xi]

# %% ../../nbs/CLI/plot.ipynb 55
@mc_logger
def pc_pyramid(
    pc:str, # path to point cloud data, 1D array (one single pc image) or 2D zarr array (a stack of pc images)
    out_dir:str, # output directory to store rendered data
    x:str=None, # path to x coordinate, e.g., longitude or web mercator x
    y:str=None, # path to y coordinate, e.g., latitude or web mercator y
    yx:str=None, # path to x and y coordinates. this coordinates should have shape [n_points,2]. e.g., gix
    ras_resolution:float=20, # minimum resolution of rendered raster data,
    ras_chunks:tuple[int,int]=(256,256), # output raster tile size
    pc_chunks:int=65536, # output pc tile size
    processes=False, # use process for dask worker over thread
    n_workers=1, # number of dask worker
    threads_per_worker=2, # number of threads per dask worker
    **dask_cluster_arg, # other dask local cluster args
):
    '''render point cloud data to pyramid of difference zoom levels.'''
    logger = logging.getLogger(__name__)
    out_dir = Path(out_dir); out_dir.mkdir(exist_ok=True)
    pc_zarr = zarr.open(pc,'r')
    logger.zarr_info(pc, pc_zarr)
    
    n_pc = pc_zarr.shape[0]
    channel_chunks = (1,)*(pc_zarr.ndim-1)
    logger.info(f'rendering point cloud data coordinates:')
    if x is None and y is None:
        yx = zarr.open(yx,'r')[:]
    else:
        y_zarr = zarr.open(y,'r')
        yx = np.empty((y_zarr.shape[0],2),dtype=y_zarr.dtype)
        yx[:,0] = zarr.open(y,'r')[:]
        yx[:,1] = zarr.open(x,'r')[:]
    x, y = yx[:,1], yx[:,0]

    x0, xm, y0, ym = x.min(), x.max(), y.min(), y.max()
    nx, ny = math.ceil((xm-x0)/ras_resolution), math.ceil((ym-y0)/ras_resolution)
    coord = Coord(x0, ras_resolution, nx, y0, ras_resolution, ny)
    bounds = {'bounds':[x0, y0, coord.xm, coord.ym]}
    logger.info(f"rasterizing point cloud data to grid with bounds: {bounds['bounds']}.")
    with open(out_dir/'bounds.toml','w') as f:
        toml.dump(bounds, f, encoder=toml.TomlNumpyEncoder())

    gix = coord.coords2gixs(yx)
    maxlevel = coord.maxlevel

    with LocalCluster(processes=processes,
                      n_workers=n_workers,
                      threads_per_worker=threads_per_worker,
                      **dask_cluster_arg) as cluster, Client(cluster) as client:
        logger.info('dask local cluster started.')
        logger.dask_cluster_info(cluster)
        output_futures = []
        x_darr, y_darr = da.from_array(x,chunks=pc_chunks), da.from_array(y,chunks=pc_chunks)
        output_futures.append(da.to_zarr(x_darr, out_dir/f'x.zarr', compute=False, overwrite=True))
        output_futures.append(da.to_zarr(y_darr, out_dir/f'y.zarr', compute=False, overwrite=True))
        logger.info('pc data coordinates rendering ends.')

        pc_darr = da.from_zarr(pc,chunks=(n_pc,*channel_chunks))
        out_pc_darr = pc_darr.rechunk((pc_chunks,*channel_chunks))
        output_futures.append(da.to_zarr(out_pc_darr, out_dir/f'pc.zarr', compute=False, overwrite=True))
        logger.info('pc data rendering ends.')

        delayed_next_idx = delayed(_next_level_idx_from_raster_of_integer,pure=True,nout=2)
        for level in range(maxlevel+1):
            if level == 0:
                current_ras = pc_darr.map_blocks(coord.rasterize, gix, dtype=pc_darr.dtype, chunks=(ny,nx,*channel_chunks))
                current_idx = da.from_array(coord.rasterize_iidx(gix), chunks=(ny,nx))
            else:
                last_idx_delayed = last_idx.to_delayed()
                yi, xi = np.empty((1,1),dtype=object), np.empty((1,1),dtype=object)
                yi_, xi_ = delayed_next_idx(last_idx_delayed[0,0],-1)
                shape = (math.ceil(ny/(2**level)), math.ceil(nx/(2**level)))
                yi_ = da.from_delayed(yi_,shape=shape,meta=np.array((),dtype=np.int32))
                xi_ = da.from_delayed(xi_,shape=shape,meta=np.array((),dtype=np.int32))
                yi[0,0] = yi_; xi[0,0] = xi_
                yi, xi = da.block(yi.tolist()), da.block(xi.tolist())
                
                current_ras = last_ras.map_blocks(_next_ras, yi, xi, dtype=last_ras.dtype, chunks=(*shape, *channel_chunks))
                current_idx = last_idx.map_blocks(_next_ras, yi, xi, dtype=last_idx.dtype, chunks=shape)

            out_current_ras = current_ras.rechunk((*ras_chunks, *channel_chunks))
            out_current_idx = current_idx.rechunk(ras_chunks)
            logger.darr_info(f'rasterized pc data at level {level}', out_current_ras)
            logger.darr_info(f'rasterized pc index at level {level}', out_current_idx)
            output_futures.append(da.to_zarr(out_current_ras, out_dir/f'{level}.zarr', compute=False, overwrite=True))
            output_futures.append(da.to_zarr(out_current_idx, out_dir/f'idx_{level}.zarr', compute=False, overwrite=True))
            last_ras = current_ras
            last_idx = current_idx

        logger.info('computing graph setted. doing all the computing.')
        futures = client.persist(output_futures)
        progress(futures,notebook=False)
        time.sleep(0.1)
        da.compute(futures)
        logger.info('computing finished.')
    logger.info('dask cluster closed.')

# %% ../../nbs/CLI/plot.ipynb 60
def _is_nan_range(x_range):
    if x_range is None:
        return True
    if np.isnan(x_range[0]):
        return True
    if abs(x_range[1]-x_range[0]) == 0:
        return True
    return False

# %% ../../nbs/CLI/plot.ipynb 61
def _hv_pc_Image_callback_0(x_range,y_range,width,height,scale,data_dir,post_proc_ras,coord,level_increase):
    if _is_nan_range(x_range):
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if _is_nan_range(y_range):
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res/coord.dx,y_res/coord.dy)))
    level += level_increase
    level = sorted((-1, level, coord.maxlevel))[1]
    # level = -1
    images = []
    if level > -1:
        data_zarr = zarr.open(data_dir/f'{level}.zarr','r')
        idx_zarr = zarr.open(data_dir/f'idx_{level}.zarr','r')
        xi0, yi0, xim, yim = coord.hv_bbox2gix_bbox((x0,y0,xm,ym),level)
        x0, y0, xm, ym = coord.gix_bbox2hv_bbox((xi0, yi0, xim, yim),level)
        data = post_proc_ras(data_zarr,slice(xi0,xim+1),slice(yi0,yim+1))
        idx = idx_zarr[yi0:yim+1,xi0:xim+1]
        return hv.Image((np.linspace(x0,xm,data.shape[1]), np.linspace(y0,ym,data.shape[0]),data,idx),vdims=['z','idx'])
    else:
        return hv.Image([],vdims=['z','idx'])
def _hv_pc_Image_callback_1(x_range,y_range,width,height,scale,data_dir,post_proc_ras,coord,level_increase,i):
    if _is_nan_range(x_range):
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if _is_nan_range(y_range):
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res/coord.dx,y_res/coord.dy)))
    level += level_increase
    level = sorted((-1, level, coord.maxlevel))[1]
    images = []
    if level > -1:
        data_zarr = zarr.open(data_dir/f'{level}.zarr','r')
        idx_zarr = zarr.open(data_dir/f'idx_{level}.zarr','r')
        xi0, yi0, xim, yim = coord.hv_bbox2gix_bbox((x0,y0,xm,ym),level)
        x0, y0, xm, ym = coord.gix_bbox2hv_bbox((xi0, yi0, xim, yim),level)
        data = post_proc_ras(data_zarr,slice(xi0,xim+1),slice(yi0,yim+1),i)
        idx = idx_zarr[yi0:yim+1,xi0:xim+1]
        return hv.Image((np.linspace(x0,xm,data.shape[1]), np.linspace(y0,ym,data.shape[0]),data,idx),vdims=['z','idx'])
    else:
        return hv.Image([],vdims=['z','idx'])
def _hv_pc_Image_callback_2(x_range,y_range,width,height,scale,data_dir,post_proc_ras,coord,level_increase,i,j):
    if _is_nan_range(x_range):
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if _is_nan_range(y_range):
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res/coord.dx,y_res/coord.dy)))
    level += level_increase
    level = sorted((-1, level, coord.maxlevel))[1]
    images = []
    if level > -1:
        data_zarr = zarr.open(data_dir/f'{level}.zarr','r')
        idx_zarr = zarr.open(data_dir/f'idx_{level}.zarr','r')
        xi0, yi0, xim, yim = coord.hv_bbox2gix_bbox((x0,y0,xm,ym),level)
        x0, y0, xm, ym = coord.gix_bbox2hv_bbox((xi0, yi0, xim, yim),level)
        data = post_proc_ras(data_zarr,slice(xi0,xim+1),slice(yi0,yim+1),i,j)
        idx = idx_zarr[yi0:yim+1,xi0:xim+1]
        return hv.Image((np.linspace(x0,xm,data.shape[1]), np.linspace(y0,ym,data.shape[0]),data,idx),vdims=['z','idx'])
    else:
        return hv.Image([],vdims=['z','idx'])

# %% ../../nbs/CLI/plot.ipynb 62
def _hv_pc_Points_callback_0(x_range,y_range,width,height,scale,data_dir,post_proc_pc,coord,rtree,level_increase):
    if _is_nan_range(x_range):
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if _is_nan_range(y_range):
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res/coord.dx,y_res/coord.dy)))
    level += level_increase
    level = sorted((-1, level, coord.maxlevel))[1]
    images = []
    if level > -1:
        return hv.Points([],vdims=['z','idx'])
    else:
        data_zarr, x_zarr, y_zarr = (zarr.open(data_dir/file,'r') for file in ('pc.zarr', 'x.zarr', 'y.zarr'))
        idx = rtree.bbox_query((x0, y0, xm, ym), x_zarr, y_zarr)
        x, y = (zarr_[idx] for zarr_ in (x_zarr, y_zarr))
        data = post_proc_pc(data_zarr,idx)
        return hv.Points((x,y,data,idx),vdims=['z','idx'])
def _hv_pc_Points_callback_1(x_range,y_range,width,height,scale,data_dir,post_proc_pc,coord,rtree,level_increase,i=0):
    if _is_nan_range(x_range):
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if _is_nan_range(y_range):
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res/coord.dx,y_res/coord.dy)))
    level += level_increase
    level = sorted((-1, level, coord.maxlevel))[1]
    # level = -1
    images = []
    if level > -1:
        return hv.Points([],vdims=['z','idx'])
    else:
        data_zarr, x_zarr, y_zarr = (zarr.open(data_dir/file,'r') for file in ('pc.zarr', 'x.zarr', 'y.zarr'))
        idx = rtree.bbox_query((x0, y0, xm, ym), x_zarr, y_zarr)
        x, y = (zarr_[idx] for zarr_ in (x_zarr, y_zarr))
        data = post_proc_pc(data_zarr,idx,i)
        return hv.Points((x,y,data,idx),vdims=['z','idx'])
def _hv_pc_Points_callback_2(x_range,y_range,width,height,scale,data_dir,post_proc_pc,coord,rtree,level_increase,i=0,j=0):
    if _is_nan_range(x_range):
        x0 = coord.x0; xm = coord.xm
    else:
        x0, xm = x_range
    if _is_nan_range(y_range):
        y0 = coord.y0; ym = coord.ym
    else:
        y0, ym = y_range
    if height is None: height = hv.plotting.bokeh.ElementPlot.height
    if width is None: width = hv.plotting.bokeh.ElementPlot.width

    x_res = (xm-x0)/width; y_res = (ym-y0)/height
    level = math.floor(math.log2(min(x_res/coord.dx,y_res/coord.dy)))
    level += level_increase
    level = sorted((-1, level, coord.maxlevel))[1]
    # level = -1
    images = []
    if level > -1:
        return hv.Points([],vdims=['z','idx'])
    else:
        data_zarr, x_zarr, y_zarr = (zarr.open(data_dir/file,'r') for file in ('pc.zarr', 'x.zarr', 'y.zarr'))
        idx = rtree.bbox_query((x0, y0, xm, ym), x_zarr, y_zarr)
        x, y = (zarr_[idx] for zarr_ in (x_zarr, y_zarr))
        data = post_proc_pc(data_zarr,idx,i,j)
        return hv.Points((x,y,data,idx),vdims=['z','idx'])

# %% ../../nbs/CLI/plot.ipynb 63
def _default_pc_post_proc(data_zarr, idx_array, *kdims):
    data_n_kdim = data_zarr.ndim - 1
    assert len(kdims) == data_n_kdim
    if len(kdims) == 0:
        return data_zarr[idx_array]
    else:
        return data_zarr[idx_array,kdims]

# %% ../../nbs/CLI/plot.ipynb 64
def _pc_inf_0_post_proc(data_zarr, idx_array, *kdims):
    data_n_kdim = data_zarr.ndim - 1
    assert len(kdims) == 1
    i = kdims[0]
    if data_n_kdim == 1:
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[idx_array,i]*data_zarr[idx_array,0].conj())
        else:
            return data_zarr[idx_array,i]-data_zarr[idx_array,0]
    else:
        assert data_n_kdim == 2
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[idx_array,i,0])
        else:
            return data_zarr[idx_array,i,0]

def _pc_inf_seq_post_proc(data_zarr, idx_array, *kdims):
    data_n_kdim = data_zarr.ndim - 1
    assert len(kdims) == 1
    i = kdims[0]
    if data_n_kdim == 1:
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[idx_array,i]*data_zarr[idx_array,i-1].conj())
        else:
            return data_zarr[idx_array,i]-data_zarr[idx_array,i-1]
    else:
        assert data_n_kdim == 2
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[idx_array,i,i-1])
        else:
            return data_zarr[idx_array,i,i-1]

def _pc_inf_all_post_proc(data_zarr, idx_array, *kdims):
    data_n_kdim = data_zarr.ndim - 1
    assert len(kdims) == 2
    i,j = kdims
    if data_n_kdim == 1:
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[idx_array,i]*data_zarr[idx_array,j].conj())
        else:
            return data_zarr[idx_array,i]-data_zarr[idx_array,j]
    else:
        assert data_n_kdim == 2
        if np.iscomplexobj(data_zarr):
            return np.angle(data_zarr[idx_array,i,j])
        else:
            return data_zarr[idx_array,i,j]

# %% ../../nbs/CLI/plot.ipynb 65
def pc_plot(
    pyramid_dir:str, # directory to the rendered point cloud pyramid
    post_proc_ras:Callable=None, # function for the post processing
    post_proc_pc:Callable=None, # function for the post processing
    n_kdim:int=None, # number of key dimensions, can only be 0 or 1 or 2, ndim of point cloud dataset -1 by default
    rtree=None, # rtree, if not provide, will be automatically generated but may slow the program
    level_increase=0, # amount of zoom level increase for more clear point show and faster responds time
):
    '''plot rendered point cloud pyramid.'''    
    if post_proc_ras is None: post_proc_ras = _default_ras_post_proc
    if post_proc_pc is None: post_proc_pc = _default_pc_post_proc

    pyramid_dir = Path(pyramid_dir)
    data_zarr = zarr.open(pyramid_dir/'0.zarr','r')
    ny, nx = data_zarr.shape[:2]

    if post_proc_ras is None:
        post_proc_ras = _default_ras_post_proc
        post_proc_pc = _default_pc_post_proc
    elif post_proc_ras == 'intf_0':
        post_proc_ras = _ras_inf_0_post_proc
        post_proc_pc = _pc_inf_0_post_proc
        n_kdim = 1
    elif post_proc_ras == 'intf_seq':
        post_proc_ras = _ras_inf_seq_post_proc
        post_proc_pc = _pc_inf_seq_post_proc
        n_kdim = 1
    elif post_proc_ras == 'intf_all':
        post_proc_ras = _ras_inf_all_post_proc
        post_proc_pc = _pc_inf_all_post_proc
        n_kdim = 2

    if n_kdim is None: n_kdim = data_zarr.ndim -2
    assert n_kdim <= 2, 'n_kdim can only be 0 or 1 or2.'
    kdims = ['i','j'][:n_kdim]
    
    with open(pyramid_dir/'bounds.toml','r') as f:
        x0, y0, xm, ym = toml.load(f)['bounds']

    dx = (xm-x0)/(nx-1); dy = (ym-y0)/(ny-1)
    coord = Coord(x0,dx,nx,y0,dy,ny)
    
    if rtree is None:
        x = zarr.open(pyramid_dir/'x.zarr','r')[:]
        y = zarr.open(pyramid_dir/'y.zarr','r')[:]
        rtree = HilbertRtree.build(x,y,page_size=512)

    if len(kdims) == 0:
        hv_pc_Image_callback = _hv_pc_Image_callback_0
        hv_pc_Points_callback = _hv_pc_Points_callback_0
    elif len(kdims) == 1:
        hv_pc_Image_callback = _hv_pc_Image_callback_1
        hv_pc_Points_callback = _hv_pc_Points_callback_1
    elif len(kdims) == 2:
        hv_pc_Image_callback = _hv_pc_Image_callback_2
        hv_pc_Points_callback = _hv_pc_Points_callback_2

    rangexy = streams.RangeXY()
    plotsize = streams.PlotSize()
    images = hv.DynamicMap(partial(hv_pc_Image_callback,data_dir=pyramid_dir,
                                   post_proc_ras=post_proc_ras,coord=coord,level_increase=level_increase),
                           streams=[rangexy,plotsize],kdims=kdims)
    points = hv.DynamicMap(partial(hv_pc_Points_callback,data_dir=pyramid_dir,
                                   post_proc_pc=post_proc_pc,coord=coord,rtree=rtree,level_increase=level_increase),
                           streams=[rangexy,plotsize],kdims=kdims)
    return images*points
