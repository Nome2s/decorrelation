# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/API/plot.ipynb.

# %% auto 0
__all__ = ['raster', 'raster_stack', 'points', 'points_stack', 'bg_alpha']

# %% ../nbs/API/plot.ipynb 3
import numpy as np
import pandas as pd
from typing import Union

import holoviews as hv
import holoviews.operation.datashader as hd
import datashader as ds

# %% ../nbs/API/plot.ipynb 10
def raster(p:np.ndarray, # data to be plot, shape (n,m)
           kdims:list=None,# name of coordinates (x, y), ['x','y']by default
           pdim:str=None, # name of data to be plotted, 'z' by default
           bounds:tuple=None, # extent of the raster, (x0, y0, x1 and y1), (0,0,m,n) )by default
           prange:tuple=None, # range of data to be plotted, it is interactively adjusted by default
           aggregator=ds.first, # aggregator for data rasterization
           use_hover:bool=True, # use hover to show data
):
    '''Interative visulization of a raster image.
    '''
    if kdims is None: kdims = ['x','y']
    if pdim is None: pdim = 'z'
    if prange is None: prange = (None, None)
    # if extents is None: extents = (None, None, None, None)
    if bounds is None: bounds = (0-0.5, 0-0.5, p.shape[1]+0.5, p.shape[0]+0.5)
    # if bounds is None: bounds = (0, p.shape[0], p.shape[1], 0)
    ## many problem to be solved:
    ##  1. the integer tiks should be at the center of pixel, but not
    ##  2. What does the bounds mean? center of the pixel or upper left of the pixel
    ##  3. The place of the inspect point is not at the center of the pixel
    ## now, no pixel-wise accurate rendering.
    vdims = [hv.Dimension(pdim,range=prange)]
    plot = hv.Image(p[::-1,:],bounds=bounds, kdims=kdims, vdims=vdims)
    plot = hd.rasterize(plot,aggregator=aggregator(),vdim_prefix='')
    if use_hover:
        highlight = hd.inspect_points(plot).opts(marker='o',size=10,tools=['hover'])
        plot = plot*highlight
    return plot

# %% ../nbs/API/plot.ipynb 14
def raster_stack(p:np.ndarray, # data to be plot, shape (n,m,l)
                 kdims:list=None,# name of coordinates (x, y), ['x','y'] by default
                 tdim:str=None, # name of coordiantes (t,), 't' by default
                 pdim:str=None, # name of data to be plotted, 'z' by default
                 bounds:tuple=None, # extent of the raster, (x0, y0, x1 and y1), (0,0,m,n) )by default
                 t:list=None, # t coordinate of the plot, len: l, list of string. ['0','1',...] by default
                 prange:tuple=None, # range of data to be plotted, it is interactively adjusted by default
                 aggregator=ds.first, # aggregator for data rasterization
                 use_hover:bool=True, # use hover to show data
                ):
    '''Interative visulization of a raster image.
    '''
    if kdims is None: kdims = ['x','y']
    if tdim is None: tdim = 't'
    if pdim is None: pdim = 'z'
    if prange is None: prange = (None, None)
    if bounds is None: bounds = (0, p.shape[0], p.shape[1], 0)
    if t is None: t = map(str, np.arange(p.shape[2]))
    vdims = [hv.Dimension(pdim,range=prange)]

    plot_stack = {}
    for i, date in enumerate(t):
        plot_stack[date] = hv.Image(p[::-1,:,i], bounds=bounds, kdims=kdims,vdims=vdims)

    hmap = hv.HoloMap(plot_stack, kdims=pdim)
    hmap = hd.rasterize(hmap, aggregator=aggregator(),vdim_prefix='')

    if use_hover:
        highlight = hd.inspect_points(hmap).opts(marker='o',size=10,tools=['hover'])
        hmap = hmap*highlight

    return hmap

# %% ../nbs/API/plot.ipynb 19
def points(data:pd.DataFrame, # dataset to be plot
           kdims:list,# colomn name of Mercator coordinate in dataframe
           pdim:str, # column name of data to be plotted in dataframe
           prange:tuple=None, # range of data to be plotted, it is interactively adjusted by default
           aggregator=ds.first, # aggregator for data rasterization
           use_hover:bool=True, # use hover to show data
           vdims:list=None, # column name of data showed on hover except kdims and pdim. These two are always showed.
           google_earth:bool=False, # if use google earth imagery as the background
           ):
    '''Interative visulization of a point cloud image.
    '''
    if prange is None: prange = (None, None)
    if vdims is None: vdims = []
    if pdim in vdims: vdims.remove(pdim)
    vdims = [hv.Dimension(pdim,range=prange)] + vdims
    points = hv.Points(data,kdims=kdims, vdims=vdims)
    points = hd.rasterize(points,aggregator=aggregator(pdim),vdim_prefix='')
    points = hd.dynspread(points, max_px=5, threshold=0.2)
    if use_hover:
        highlight = hd.inspect_points(points).opts(marker='o',size=10,tools=['hover'])
        points = points*highlight
    if google_earth:
        geo_bg = hv.Tiles('https://mt1.google.com/vt/lyrs=s&x={X}&y={Y}&z={Z}',name='GoogleMapsImagery')
        points = geo_bg*points
    return points

# %% ../nbs/API/plot.ipynb 25
def points_stack(data:pd.DataFrame, # common data in all plots
                 kdims:list,# colomn name of Mercator coordinate in dataframe
                 pdata:pd.DataFrame, # data to be plotted as color
                 pdim:str, # label of pdata
                 prange:tuple=None, # range of pdata, it is interactively adjusted by default
                 aggregator=ds.first, # aggregator for data rasterization
                 use_hover:bool=True, # use hover to show other column
                 vdims:list=None, # column name of data showed on hover except kdims which are always showed.
                 google_earth:bool=False, # if use google earth imagery as the background
                ):
    '''Interative visulization of a stack of point cloud images.
    '''
    if prange is None: prange = (None, None)
    if vdims is None: vdims = []
    if pdim in vdims: vdims.remove(pdim)
    vdims = [hv.Dimension(pdim,range=prange)] + vdims

    plot_stack = {}
    for (name, column) in pdata.items():
        _data = data.copy(deep=False)
        _data[pdim] = column
        plot_stack[name] = hv.Points(_data,kdims=kdims,vdims=vdims)

    hmap = hv.HoloMap(plot_stack, kdims=pdim)
    hmap = hd.rasterize(hmap, aggregator=aggregator(pdim),vdim_prefix='')
    hmap = hd.dynspread(hmap, max_px=5, threshold=0.2)

    if use_hover:
        highlight = hd.inspect_points(hmap).opts(marker='o',size=10,tools=['hover'])
        hmap = hmap*highlight
    if google_earth:
        geo_bg = hv.Tiles('https://mt1.google.com/vt/lyrs=s&x={X}&y={Y}&z={Z}',name='GoogleMapsImagery')
        hmap = geo_bg*hmap
    return hmap

# %% ../nbs/API/plot.ipynb 33
def bg_alpha(pwr):
    _pwr = np.power(pwr,0.35)
    cv = _pwr.mean()*2.5
    v = (_pwr.clip(0., cv))/cv
    return v