# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/API/shp.ipynb.

# %% auto 0
__all__ = ['ks_test', 'select_shp']

# %% ../nbs/API/shp.ipynb 4
import numpy as np
from .utils_ import is_cuda_available, get_array_module
if is_cuda_available():
    import cupy as cp
import math
import numba
from numba import prange
from .utils_ import ngpjit, ngjit

# %% ../nbs/API/shp.ipynb 6
@ngjit
def _ks_p_numba(x):
    x2 = -2*x*x
    p = 0.0
    p2 = 0.0
    sign = 1
    for i in range(1,101):
        p += sign*2*math.exp(x2*i*i)
        if (p == p2):
            return p
        else:
            sign = -sign
            p2 = p
    return p

# %% ../nbs/API/shp.ipynb 7
@ngjit
def _ks_d_numba(ref, sec, n_imag):
    j1 = 0; j2 = 0; d = 0.0; dmax = 0.0
    while (j1 < n_imag) and (j2 < n_imag):
        f1 = ref[j1]; f2 = sec[j2]
        if f1 <= f2: j1 += 1;
        if f1 >= f2: j2 += 1;
        d = abs((j2-j1)/n_imag)
        if (d > dmax): dmax = d
    return dmax

# %% ../nbs/API/shp.ipynb 8
@ngpjit
def _ks_test_no_dist_numba(
    rmli, # sorted rmli stack
    az_half_win,
    r_half_win,
):
    n_az, n_r,n_imag = rmli.shape
    p = np.empty((n_az,n_r,2*az_half_win+1,2*r_half_win+1),dtype=rmli.dtype)
    for i in prange(n_az):
        for j in prange(n_r):
            ref_rmli = rmli[i,j]
            if math.isnan(ref_rmli[-1]):
                for l in range(-az_half_win, az_half_win+1):
                    for m in range(-r_half_win,r_half_win+1):
                        p[i,j,l+az_half_win,m+r_half_win] = np.nan
            else:
                for l in range(-az_half_win, az_half_win+1):
                    for m in range(-r_half_win,r_half_win+1):
                        sec_i = i+l
                        sec_j = j+m
                        if (sec_i<0) or (sec_i>=n_az) or (sec_j<0) or (sec_j>=n_r):
                            p[i,j,l+az_half_win,m+r_half_win] = np.nan
                        else:
                            sec_rmli = rmli[sec_i, sec_j]
                            if math.isnan(sec_rmli[-1]):
                                p[i,j,l+az_half_win,m+r_half_win] = np.nan
                            else:
                                dmax = _ks_d_numba(ref_rmli, sec_rmli, n_imag)
                                en = math.sqrt(n_imag/2)
                                p[i,j,l+az_half_win,m+r_half_win] = _ks_p_numba((en+0.12+0.11/en)*dmax)
    return p

@ngpjit
def _ks_test_numba(
    rmli, # sorted rmli stack
    az_half_win,
    r_half_win,
):
    n_az, n_r,n_imag = rmli.shape
    dist = np.empty((n_az,n_r,2*az_half_win+1,2*r_half_win+1),dtype=rmli.dtype)
    p = np.empty((n_az,n_r,2*az_half_win+1,2*r_half_win+1),dtype=rmli.dtype)
    for i in prange(n_az):
        for j in prange(n_r):
            ref_rmli = rmli[i,j]
            if math.isnan(ref_rmli[-1]):
                for l in range(-az_half_win, az_half_win+1):
                    for m in range(-r_half_win,r_half_win+1):
                        dist[i,j,l+az_half_win,m+r_half_win] = np.nan
                        p[i,j,l+az_half_win,m+r_half_win] = np.nan
            else:
                for l in range(-az_half_win, az_half_win+1):
                    for m in range(-r_half_win,r_half_win+1):
                        sec_i = i+l
                        sec_j = j+m
                        if (sec_i<0) or (sec_i>=n_az) or (sec_j<0) or (sec_j>=n_r):
                            dist[i,j,l+az_half_win,m+r_half_win] = np.nan
                            p[i,j,l+az_half_win,m+r_half_win] = np.nan
                        else:
                            sec_rmli = rmli[sec_i, sec_j]
                            if math.isnan(sec_rmli[-1]):
                                p[i,j,l+az_half_win,m+r_half_win] = np.nan
                            else:
                                dmax = _ks_d_numba(ref_rmli, sec_rmli, n_imag)
                                en = math.sqrt(n_imag/2)
                                dist[i,j,l+az_half_win,m+r_half_win] = dmax
                                p[i,j,l+az_half_win,m+r_half_win] = _ks_p_numba((en+0.12+0.11/en)*dmax)
    return dist, p

# %% ../nbs/API/shp.ipynb 9
@ngpjit
def _sort_numba(
    rmli, # rmli stack
):
    n_az, n_r,n_imag = rmli.shape
    sorted_rmli = np.empty_like(rmli)
    for i in prange(n_az):
        for j in prange(n_r):
            sorted_rmli[i,j] = np.sort(rmli[i,j])
    return sorted_rmli

# %% ../nbs/API/shp.ipynb 10
# It looks cupy do not support pointer to pointer: float** rmli_stack
if is_cuda_available():
    _ks_test_kernel = cp.ElementwiseKernel(
        'raw T rmli_stack, int32 nlines, int32 width, int32 nimages, int32 az_half_win, int32 r_half_win',
        'raw T dist, raw T p',
        '''
        int az_win = 2*az_half_win+1;
        int r_win = 2*r_half_win+1;
        int win = az_win*r_win;
        
        int ref_idx = i/win;
        int ref_az = ref_idx/width;
        int ref_r = ref_idx -ref_az*width;
        
        int win_idx = i - ref_idx*win;
        int win_az = win_idx/r_win;
        int win_r = win_idx - win_az*r_win;
        int sec_az = ref_az + win_az - az_half_win;
        int sec_r = ref_r + win_r - r_half_win;
        int sec_idx = sec_az*width + sec_r;
        
        if (ref_r >= width && ref_az >= nlines) {
            return;
        }
        if (sec_az < 0 || sec_az >= nlines || sec_r < 0 || sec_r >= width) {
            dist[ref_idx*win+win_az*r_win+win_r] = CUDART_NAN;
            p[ref_idx*win+win_az*r_win+win_r] = CUDART_NAN;
            return;
        }

        // if data contain nan value, nan are sorted to the end
        if (isnan(rmli_stack[ref_idx*nimages + nimages-1]) || isnan(rmli_stack[sec_idx*nimages + nimages-1])) {
            dist[ref_idx*win+win_az*r_win+win_r] = CUDART_NAN;
            p[ref_idx*win+win_az*r_win+win_r] = CUDART_NAN;
            return;
        }

        // Compute the maximum difference between the cumulative distributions
        int j1 = 0, j2 = 0;
        T f1, f2, d, dmax = 0.0, en = nimages;
    
        while (j1 < nimages && j2 < nimages) {
            f1 = rmli_stack[ref_idx*nimages + j1];
            f2 = rmli_stack[sec_idx*nimages + j2];
            if (f1 <= f2) j1++;
            if (f1 >= f2) j2++;
            d = fabs((j2-j1)/en);
            if (d > dmax) dmax = d;
        }
        en=sqrt(en/2);
        p[ref_idx*win+win_az*r_win+win_r] = ks_p((en+0.12+0.11/en)*dmax);
        dist[ref_idx*win+win_az*r_win+win_r] = dmax;
        ''',
        name = 'ks_test_kernel',no_return=True,
        preamble = '''
        #include <cupy/math_constants.h>
        __device__ T ks_p(T x)
        {
            T x2 = -2.0*x*x;
            int sign = 1;
            T p = 0.0,p2 = 0.0;
        
            for (int i = 1; i <= 100; i++) {
                p += sign*2*exp(x2*i*i);
                if (p==p2) return p;
                sign = -sign;
                p2 = p;
            }
            return p;
        }
        ''',)
    _ks_test_no_dist_kernel = cp.ElementwiseKernel(
        'raw T rmli_stack, int32 nlines, int32 width, int32 nimages, int32 az_half_win, int32 r_half_win',
        'raw T p',
        '''
        int az_win = 2*az_half_win+1;
        int r_win = 2*r_half_win+1;
        int win = az_win*r_win;
        
        int ref_idx = i/win;
        int ref_az = ref_idx/width;
        int ref_r = ref_idx -ref_az*width;
        
        int win_idx = i - ref_idx*win;
        int win_az = win_idx/r_win;
        int win_r = win_idx - win_az*r_win;
        int sec_az = ref_az + win_az - az_half_win;
        int sec_r = ref_r + win_r - r_half_win;
        int sec_idx = sec_az*width + sec_r;
        
        if (ref_r >= width && ref_az >= nlines) {
            return;
        }
        if (sec_az < 0 || sec_az >= nlines || sec_r < 0 || sec_r >= width) {
            p[ref_idx*win+win_az*r_win+win_r] = CUDART_NAN;
            return;
        }

        // if data contain nan value, nan are sorted to the end
        if (isnan(rmli_stack[ref_idx*nimages + nimages-1]) || isnan(rmli_stack[sec_idx*nimages + nimages-1])) {
            p[ref_idx*win+win_az*r_win+win_r] = CUDART_NAN;
            return;
        }
        
        // Compute the maximum difference between the cumulative distributions
        int j1 = 0, j2 = 0;
        T f1, f2, d, dmax = 0.0, en = nimages;
        
        while (j1 < nimages && j2 < nimages) {
            f1 = rmli_stack[ref_idx*nimages + j1];
            f2 = rmli_stack[sec_idx*nimages + j2];
            // check if there nan value in the data

            if (f1 <= f2) j1++;
            if (f1 >= f2) j2++;
            d = fabs((j2-j1)/en);
            if (d > dmax) dmax = d;
        }
        en=sqrt(en/2);
        p[ref_idx*win+win_az*r_win+win_r] = ks_p((en+0.12+0.11/en)*dmax);
        ''',
        name = 'ks_test_no_dist_kernel',no_return=True,
        preamble = '''
        #include <cupy/math_constants.h>
        __device__ T ks_p(T x)
        {
            T x2 = -2.0*x*x;
            int sign = 1;
            T p = 0.0,p2 = 0.0;
        
            for (int i = 1; i <= 100; i++) {
                p += sign*2*exp(x2*i*i);
                if (p==p2) return p;
                sign = -sign;
                p2 = p;
            }
            return p;
        }
        ''',)

# %% ../nbs/API/shp.ipynb 11
def ks_test(rmli:np.ndarray, # the rmli stack, dtype: cupy.floating
            az_half_win:int, # SHP identification half search window size in azimuth direction
            r_half_win:int, # SHP identification half search window size in range direction
            block_size:int=128, # the CUDA block size, it only affects the calculation speed, only applied if input is cupy.ndarray
            return_dist:bool=False, # if return the KS test statistics `dist`
           ) -> tuple[np.ndarray,np.ndarray] : # if return_dist == True, return `dist` and p value `p`. Otherwise, only `p` is returned.
    '''
    SHP identification based on Two-Sample Kolmogorov-Smirnov Test.
    '''
    xp = get_array_module(rmli)
    az_win = 2*az_half_win+1
    r_win = 2*r_half_win+1
    nlines, width, nimages = rmli.shape
    if xp is np:
        sorted_rmli = _sort_numba(rmli)
        if return_dist:
            return _ks_test_numba(sorted_rmli, az_half_win, r_half_win)
        else:
            return _ks_test_no_dist_numba(sorted_rmli, az_half_win, r_half_win)

    else:
        sorted_rmli = cp.sort(rmli,axis=-1)
        if return_dist:
            dist = cp.empty((nlines,width,az_win,r_win),dtype=rmli.dtype)
            p = cp.empty((nlines,width,az_win,r_win),dtype=rmli.dtype)
        
            _ks_test_kernel(sorted_rmli,cp.int32(nlines),cp.int32(width),cp.int32(nimages),
                            cp.int32(az_half_win),cp.int32(r_half_win),dist,p,
                            size=width*nlines*r_win*az_win,block_size=block_size)
            return dist,p
        else:
            p = cp.empty((nlines,width,az_win,r_win),dtype=rmli.dtype)
        
            _ks_test_no_dist_kernel(sorted_rmli,cp.int32(nlines),cp.int32(width),cp.int32(nimages),
                            cp.int32(az_half_win),cp.int32(r_half_win),p,
                            size=width*nlines*r_win*az_win,block_size=block_size)
            return p

# %% ../nbs/API/shp.ipynb 25
@ngpjit
def select_shp(
    p, # 4D (n_az,n_r,az_win,r_win)
    p_max,
):
    p_shape = p.shape
    is_shp = np.empty(p_shape, dtype=np.bool_)
    shp_num = np.zeros(p_shape[:2], dtype=np.int32)
    for i in prange(p_shape[0]):
        for j in prange(p_shape[1]):
            for k in range(p_shape[2]):
                for l in range(p_shape[3]):
                    is_shp[i,j,k,l] = p[i,j,k,l] < p_max
                    if is_shp[i,j,k,l]:
                        shp_num[i,j] += 1
    return is_shp, shp_num
