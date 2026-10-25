import json
import ctypes
import mmap
import multiprocessing as mp
import os
import sys
import time

def busy():
    n=1
    while True:
        for _ in range(10000): n=(n*3+1)%1000000007

if __name__ == '__main__':
    page=mmap.mmap(-1,4096,prot=mmap.PROT_READ|mmap.PROT_WRITE|mmap.PROT_EXEC)
    page.write(bytes.fromhex('0faee80f3148c1e2204809d00faee8c3'))
    rdtsc=ctypes.CFUNCTYPE(ctypes.c_uint64)(ctypes.addressof(ctypes.c_char.from_buffer(page)))
    libc=ctypes.CDLL(None)
    sample=0
    cpus=sorted(os.sched_getaffinity(0))
    workers=[] if '--no-load' in sys.argv else [mp.Process(target=busy,daemon=True) for _ in cpus]
    for worker in workers: worker.start()
    try:
        for line in sys.stdin:
            os.sched_setaffinity(0,{cpus[sample%len(cpus)]})
            print(json.dumps({'monotonic':time.monotonic(),'realtime':time.time(),'tsc':rdtsc(),'cpu':libc.sched_getcpu()}),flush=True)
            sample+=1
    finally:
        for worker in workers: worker.terminate()
        for worker in workers: worker.join()
