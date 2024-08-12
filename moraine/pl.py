# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/API/pl.ipynb.

# %% auto 0
__all__ = ['emi', 'ds_temp_coh', 'emperical_co_emi_temp_coh_pc']

# %% ../nbs/API/pl.ipynb 5
import numpy as np
import moraine as mr
from .utils_ import is_cuda_available, get_array_module
if is_cuda_available():
    import cupy as cp
from numba import prange
from .utils_ import ngpjit

# %% ../nbs/API/pl.ipynb 8
if is_cuda_available():
    def _emi_cp(
        coh, # complex coherence metrix, dtype, cp.complex64
        n_images,
        image_pairs,
        ref:int=0,
    ):
        n_points = coh.shape[0]
        max_batch_size = 2**20
        num_batchs = np.ceil(n_points/max_batch_size).astype(int)
        ph = cp.empty((n_points,n_images),dtype=coh.dtype)
        emi_quality = cp.empty(n_points, dtype=cp.float32)
        for i in range(num_batchs):
            start = i*max_batch_size
            end = (i+1)*max_batch_size
            if end >= n_points: end = n_points
            _coh = mr.uncompress_coh(coh[start:end],image_pairs)
            coh_mag = cp.abs(_coh)
            coh_mag_inv = cp.linalg.inv(coh_mag)
            min_eigval, min_eig = cp.linalg.eigh(coh_mag_inv*_coh)
            min_eigval = min_eigval[...,0]
            min_eig = min_eig[...,0]*min_eig[...,[ref],0].conj()
            ph[start:end] = min_eig/abs(min_eig)
            emi_quality[start:end] = min_eigval
        return ph, emi_quality

# %% ../nbs/API/pl.ipynb 9
@ngpjit
def _emi_numba(
    coh,
    n_images,
    image_pairs,
    ref:int=0,
):
    n_points = coh.shape[0]
    ph = np.empty((n_points,n_images),dtype=coh.dtype)
    emi_quality = np.empty(n_points,dtype=np.float32)
    for i in prange(n_points):
        _coh = mr.uncompress_single_coh_numba(coh[i],n_images,image_pairs)
        coh_mag = np.abs(_coh)
        coh_mag_inv = np.linalg.inv(coh_mag)
        min_eigval, min_eig = np.linalg.eigh(coh_mag_inv*_coh)
        min_eigval = min_eigval[0]
        min_eig = min_eig[:,0]*np.conj(min_eig[ref,0])
        for j in range(ph.shape[-1]):
            ph[i,j] = min_eig[j]/abs(min_eig[j])
        emi_quality[i] = min_eigval
    return ph, emi_quality

# %% ../nbs/API/pl.ipynb 10
def emi(coh:np.ndarray, #complex coherence metrix,dtype cupy.complex
        ref:int=0, #index of reference image in the phase history output, optional. Default: 0
       )-> tuple[np.ndarray,np.ndarray]: # estimated phase history `ph`, dtype complex; quality (minimum eigvalue, dtype float)
    xp = get_array_module(coh)
    nimages = mr.nimage_from_npair(coh.shape[-1])
    image_pairs = mr.TempNet.from_bandwidth(nimages).image_pairs
    if xp is np:
        return _emi_numba(coh,nimages,image_pairs,ref)
    else:
        return _emi_cp(coh,nimages,image_pairs,ref)

# %% ../nbs/API/pl.ipynb 24
@ngpjit
def _ds_temp_coh_numba(
    coh:np.ndarray,# complex coherence metrix, dtype np.complex64
    ph:np.ndarray, # complex phase history, dtype np.complex64
    image_pairs:np.ndarray, # image pairs
):
    nimages = ph.shape[-1]
    n_points = ph.shape[0]
    n_image_pairs = image_pairs.shape[0]
    temp_coh = np.empty(n_points,dtype=np.float32)
    for i in prange(n_points):
        _ph = ph[i]
        _coh = coh[i]
        _t_coh = np.float32(0.0)
        for j in range(n_image_pairs):
            n, k = image_pairs[j,0],image_pairs[j,1]
            int_conj_ph = np.conjugate(_ph[n])*_ph[k]
            diff_ph = _coh[j]*int_conj_ph/np.abs(_coh[j])
            _t_coh += diff_ph.real
        _t_coh = _t_coh/n_image_pairs
        temp_coh[i] = _t_coh
    return temp_coh

# %% ../nbs/API/pl.ipynb 25
if is_cuda_available():
    _ds_temp_coh_kernel = cp.ElementwiseKernel(
        'raw T coh, raw T ph, raw I image_pairs, int32 n_points, int32 nimages, int32 n_image_pairs',
        'raw float32 temp_coh',
        '''
        if (i >= n_points) return;
        float _t_coh = 0;
        int j; int n; int k;
        int coh_idx; int ph_n_idx; int ph_k_idx;
        for (j = 0; j< n_image_pairs; j++){
            n = image_pairs[j*2];
            k = image_pairs[j*2+1];
            coh_idx = i*n_image_pairs+j;
            ph_n_idx = i*nimages+n;
            ph_k_idx = i*nimages+k;
            _t_coh += real(coh[coh_idx]/sqrt(norm(coh[coh_idx]))*conj(ph[ph_n_idx])*ph[ph_k_idx]);
        }
        temp_coh[i] = _t_coh/n_image_pairs;
        ''',
        name = 'ds_temp_coh_kernel',no_return=True,
    )

# %% ../nbs/API/pl.ipynb 26
def ds_temp_coh(coh:np.ndarray,# complex coherence metrix, np.complex64 or cp.complex64
                ph:np.ndarray, # complex phase history, np.complex64 or cp.complex64
                image_pairs:np.ndarray=None, # image pairs, all image pairs by default
                block_size:int=128, # the CUDA block size, only applied for cuda
            ):
    xp = get_array_module(coh)
    n_points = ph.shape[0]
    nimages = ph.shape[-1]
    if image_pairs is None:
        image_pairs = mr.TempNet.from_bandwidth(nimages).image_pairs
    image_pairs = image_pairs.astype(np.int32)
    
    if xp is np:
        return _ds_temp_coh_numba(coh,ph,image_pairs)
    else:
        image_pairs = cp.asarray(image_pairs)
        n_image_pairs = image_pairs.shape[0]
        temp_coh = cp.empty(n_points, dtype=cp.float32)
        _ds_temp_coh_kernel(coh, ph, image_pairs, cp.int32(n_points),cp.int32(nimages),cp.int32(n_image_pairs), temp_coh, size=n_points, block_size=block_size)
        return temp_coh

# %% ../nbs/API/pl.ipynb 33
def emperical_co_emi_temp_coh_pc(
    rslc:np.ndarray, # rslc stack, dtype:'np.complex64'
    idx:np.ndarray, # index of point target (azimuth_index, range_index), dtype: `np.int32`, shape: (n_pc, 2)
    pc_is_shp:np.ndarray, # shp bool, dtype:'np.bool'
    batch_size:int=1000,
):
    xp = get_array_module(rslc)
    n_pc = idx.shape[0]
    nimages = rslc.shape[2]
    ph = xp.empty((n_pc, nimages),dtype=xp.complex64)
    emi_quality = xp.empty(n_pc,dtype=np.float32)
    t_coh = xp.empty(n_pc,dtype=np.float32)
    batch_bounds = np.arange(0,n_pc+batch_size,batch_size)
    if batch_bounds[-1]>n_pc: batch_bounds[-1]=n_pc
    for i in range(batch_bounds.shape[0]-1):
        start = batch_bounds[i]; stop = batch_bounds[i+1]
        _coh = mr.co.emperical_co_pc(rslc,idx[start:stop],pc_is_shp[start:stop])
        ph[start:stop],emi_quality[start:stop] = emi(_coh)
        t_coh[start:stop] = ds_temp_coh(_coh,ph[start:stop])
    return ph, emi_quality, t_coh
