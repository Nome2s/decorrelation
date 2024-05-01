# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/API/pc.ipynb.

# %% auto 0
__all__ = ['pc2ras', 'pc_hix', 'pc_sort', 'pc_union', 'pc_intersect', 'pc_diff']

# %% ../nbs/API/pc.ipynb 7
import numpy as np
from numba import prange
import math
from .utils_ import is_cuda_available, get_array_module
if is_cuda_available():
    import cupy as cp
from .utils_ import ngjit, ngpjit
from .coord_ import Coord

# %% ../nbs/API/pc.ipynb 9
def pc2ras(gix:np.ndarray, # gix array
           pc_data:np.ndarray, # data, 1D or more
           shape:tuple, # image shape
          ):
    '''convert point cloud data to original raster, filled with nan'''
    xp = get_array_module(pc_data)
    raster = xp.empty((*shape,*pc_data.shape[1:]),dtype=pc_data.dtype)
    raster[:] = xp.nan
    raster[gix[0],gix[1]] = pc_data
    return raster

# %% ../nbs/API/pc.ipynb 11
def _ras_dims(gix1:np.ndarray, # int array, grid index of the first point cloud
              gix2:np.ndarray=None, # int array, grid index of the second point cloud
             )->tuple: # the shape of the original raster image
    '''Get the shape of the original raster image from two index, the shape could be smaller than the truth but it doesn't matter.'''
    xp = get_array_module(gix1)
    if gix2 is None:
        dims_az = gix1[0,-1]+1
        dims_r = int(xp.max(gix1[1,:]))+1
    else:
        dims_az = max(int(gix1[0,-1]),int(gix2[0,-1]))+1
        dims_r = max(int(xp.max(gix1[1,:])),int(xp.max(gix2[1,:])))+1
    return (dims_az,dims_r)

# %% ../nbs/API/pc.ipynb 12
# Some functions adapted from spatialpandas at https://github.com/holoviz/spatialpandas under BSD-2-Clause license,
# Which is Initially based on https://github.com/galtay/hilbert_curve, but specialized
# for 2 dimensions with numba acceleration

# Further enhanced with numba prange.
@ngjit
def _int_2_binary(v, width): # Return a binary byte array representation of `v` zero padded to `width` bits.
    res = np.zeros(width, dtype=np.uint8)
    for i in range(width):
        res[width - i - 1] = v % 2
        v = v >> 1
    return res
@ngjit
def _binary_2_int(bin_vec):
    # Convert a binary byte array to an integer
    res = 0
    next_val = 1
    width = len(bin_vec)
    for i in range(width):
        res += next_val*bin_vec[width - i - 1]
        next_val <<= 1
    return res
@ngjit
def _hilbert_integer_to_transpose(p:int, # iterations to use in the hilbert curve
                                  h:int, # integer distance along hilbert curve
                                 )->list: # x (list): transpose of h (n components with values between 0 and 2**p-1)
    #Store a hilbert integer (`h`) as its transpose (`x`).
    h_bits = _int_2_binary(h, 2*p)

    x = [_binary_2_int(h_bits[i::2]) for i in range(2)]
    return x
@ngjit
def _transpose_to_hilbert_integer(p:int, # iterations to use in the hilbert curve
                                  coord:list, # transpose of h (2 components with values between 0 and 2**p-1)
                                 )->int: # h (int): integer distance along hilbert curve
    # Restore a hilbert integer (`h`) from its transpose (`x`).
    bins = [_int_2_binary(v, p) for v in coord]
    concat = np.zeros(2*p, dtype=np.uint8)
    for i in range(p):
        for j in range(2):
            concat[2*i + j] = bins[j][i]

    h = _binary_2_int(concat)
    return h

@ngjit
def _coordinate_from_distance(p:int, # iterations to use in the hilbert curve
                              h:int, # integer distance along hilbert curve
                             )->list: # coord (list): Coordinate as length-n list
    # Return the coordinate for a hilbert distance.
    coord = _hilbert_integer_to_transpose(p, h)
    Z = 2 << (p-1)

    # Gray decode by H ^ (H/2)
    t = coord[1] >> 1
    for i in range(1, 0, -1):
        coord[i] ^= coord[i-1]
    coord[0] ^= t

    # Undo excess work
    Q = 2
    while Q != Z:
        P = Q - 1
        for i in range(1, -1, -1):
            if coord[i] & Q:
                # invert
                coord[0] ^= P
            else:
                # exchange
                t = (coord[0] ^ coord[i]) & P
                coord[0] ^= t
                coord[i] ^= t
        Q <<= 1

    return coord
@ngjit
def _distance_from_coordinate(p:int, # iterations to use in the hilbert curve
                              coord:np.ndarray, # coordinate as 1d array
                             )->int: # distance
    # Return the hilbert distance for a given coordinate.
    M = 1 << (p - 1)
    # Inverse undo excess work
    Q = M
    while Q > 1:
        P = Q - 1
        for i in range(2):
            if coord[i] & Q:
                coord[0] ^= P
            else:
                t = (coord[0] ^ coord[i]) & P
                coord[0] ^= t
                coord[i] ^= t
        Q >>= 1
    # Gray encode
    for i in range(1, 2):
        coord[i] ^= coord[i - 1]
    t = 0
    Q = M
    while Q > 1:
        if coord[1] & Q:
            t ^= Q - 1
        Q >>= 1
    for i in range(2):
        coord[i] ^= t
    h = _transpose_to_hilbert_integer(p, coord)
    return h
@ngpjit
def _coordinates_from_distances(p:int, # iterations to use in the hilbert curve
                                h:np.ndarray, # 1d array of integer distances along hilbert curve
                               )->np.ndarray: # 2d array of coordinate, each row a coordinate corresponding to associated distance value in input.
    # Return the coordinates for an array of hilbert distances.
    result = np.zeros(2, (len(h)), dtype=np.int64)
    for i in prange(len(h)):
        result[:, i] = _coordinate_from_distance(p, h[i])
    return result
@ngpjit
def _distances_from_coordinates(p:int, # iterations to use in the hilbert curve
                                coords:np.ndarray, # 2d array of coordinates, one coordinate per row
                               )->np.ndarray: # 1d array of distances
    # Return the hilbert distances for a given set of coordinates.
    coords = np.atleast_2d(coords).copy()
    result = np.zeros(coords.shape[1], dtype=np.int64)
    for i in prange(coords.shape[1]):
        coord = coords[:, i]
        result[i] = _distance_from_coordinate(p, coord)
    return result

# %% ../nbs/API/pc.ipynb 13
def pc_hix(x:np.ndarray, # horizonal coordinate
           y:np.ndarray, # vertical coordinate
           bbox:list, # [x0, y0, xm, ym]
           interval:list # [x_interval, y_interval], cell size to make every cell has only one point falled in.
          )->np.ndarray:
    '''Compute the hillbert index for point cloud data.'''
    x0, y0, xm, ym = bbox
    dx, dy = interval
    nx = math.ceil((xm-x0)/dx)
    ny = math.ceil((ym-y0)/dy)
    coord = Coord(x0,dx,nx,y0,dy,ny)
    gix = coord.coords2gixs([y,x])
    hix = _distances_from_coordinates(coord.p,gix)
    assert len(np.unique(hix)) == len(hix), "`hix` includes duplicated element. Probably `bbox` is too small or `interval` is too big." 
    return hix

# %% ../nbs/API/pc.ipynb 19
def pc_sort(idx:np.ndarray, # unsorted `gix` (2D) or `hix`(1D)
           )->np.ndarray: # indices that sort input
    '''Get the indices that sort the input.'''
    xp = get_array_module(idx)
    if idx.ndim == 2:
        dims_az = int(xp.max(idx[0,:]))+1
        dims_r = int(xp.max(idx[1,:]))+1
        idx_1d = xp.ravel_multi_index(idx,dims=(dims_az,dims_r))
    else:
        idx_1d = idx
    key = xp.argsort(idx_1d,kind='stable')
    return key

# %% ../nbs/API/pc.ipynb 23
def pc_union(idx1:np.ndarray, # int array, grid index or hillbert index of the first point cloud
             idx2:np.ndarray, # int array, grid index or hillbert index of the second point cloud
             # the union index `idx`; index of the point in output union index that originally in the first point cloud `inv_iidx`;
             # index of the point in output union index that only exist in the second point cloud `inv_iidx2`;
             # index of the point in the second input index that are not in the first input point cloud
            )->tuple: 
    '''Get the union of two point cloud dataset. For points at their intersection, pc_data1 rather than pc_data2 is copied to the result pc_data.'''
    # this function is modified from np.unique

    xp = get_array_module(idx1)
    n1 = idx1.shape[-1]; n2 = idx2.shape[-1]
    idx = xp.concatenate((idx1,idx2),axis=-1)
    if idx.ndim == 2:
        dims = _ras_dims(idx1,idx2)
        idx_1d = xp.ravel_multi_index(idx,dims=dims) # automatically the returned 1d index is in int64
    else:
        idx_1d = idx
    iidx = xp.argsort(idx_1d,kind='stable') # test shows argsort is faster than lexsort, that is why use ravel and unravel index
    idx_1d = idx_1d[iidx]

    inv_iidx = xp.empty_like(iidx)
    inv_iidx[iidx] = xp.arange(iidx.shape[0]) # idea taken from https://stackoverflow.com/questions/2483696/undo-or-reverse-argsort-python

    mask = xp.empty(idx_1d.shape, dtype=bool)
    mask[:1] = True
    mask[1:] = idx_1d[1:] != idx_1d[:-1]
    
    idx_1d = idx_1d[mask]
    
    _mask = mask[inv_iidx] # the mask in the original cat order
    mask1 = _mask[:n1]
    mask2 = _mask[n1:]
    
    imask = xp.cumsum(mask) - 1
    inv_iidx = xp.empty(mask.shape, dtype=np.int64)
    inv_iidx[iidx] = imask # inverse the mapping
    inv_iidx = inv_iidx[_mask]
    
    if idx.ndim == 2:
        idx = xp.stack(xp.unravel_index(idx_1d,dims)).astype(idx1.dtype)
    else:
        idx = idx_1d

    return idx, inv_iidx[:n1], inv_iidx[n1:], *xp.where(mask2)

# %% ../nbs/API/pc.ipynb 32
def pc_intersect(idx1:np.ndarray, # int array, grid index or hillbert index of the first point cloud
                 idx2:np.ndarray, # int array, grid index or hillbert index of the second point cloud
                 # the intersect index `idx`,
                 # index of the point in first point cloud index that also exist in the second point cloud,
                 # index of the point in second point cloud index that also exist in the first point cloud
                )->tuple:
    '''Get the intersection of two point cloud dataset.'''
    # Here I do not write the core function by myself since cupy have a different implementation of intersect1d

    xp = get_array_module(idx1)
    if idx1.ndim == 2:
        dims = _ras_dims(idx1,idx2)
        idx1_1d = xp.ravel_multi_index(idx1,dims=dims) # automatically the returned 1d index is in int64
        idx2_1d = xp.ravel_multi_index(idx2,dims=dims) # automatically the returned 1d index is in int64
    else:
        idx1_1d = idx1; idx2_1d = idx2

    idx, iidx1, iidx2 = xp.intersect1d(idx1_1d,idx2_1d,assume_unique=True,return_indices=True)
    if idx1.ndim == 2:
        idx = xp.stack(xp.unravel_index(idx,dims)).astype(idx1.dtype)
    return idx, iidx1, iidx2

# %% ../nbs/API/pc.ipynb 35
def pc_diff(idx1:np.ndarray, # int array, grid index or hillbert index of the first point cloud
            idx2:np.ndarray, # int array, grid index or hillbert index of the second point cloud
            # the diff index `idx`,
            # index of the point in first point cloud index that do not exist in the second point cloud,
           )->tuple:
    '''Get the point cloud in `idx1` that are not in `idx2`.'''
    xp = get_array_module(idx1)
    if idx1.ndim == 2:
        dims = _ras_dims(idx1,idx2)
        idx1_1d = xp.ravel_multi_index(idx1,dims=dims) # automatically the returned 1d index is in int64
        idx2_1d = xp.ravel_multi_index(idx2,dims=dims) # automatically the returned 1d index is in int64
    else:
        idx1_1d = idx1; idx2_1d = idx2
    
    mask = xp.in1d(idx1_1d, idx2_1d, assume_unique=True, invert=True)
    idx = idx1_1d[mask]
    
    if idx1.ndim == 2:
        idx = xp.stack(xp.unravel_index(idx,dims)).astype(idx1.dtype)
        
    return idx, xp.where(mask)[0]
