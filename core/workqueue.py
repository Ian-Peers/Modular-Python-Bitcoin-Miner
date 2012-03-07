# Modular Python Bitcoin Miner
# Copyright (C) 2012 Michael Sparmann (TheSeven)
#
#     This program is free software; you can redistribute it and/or
#     modify it under the terms of the GNU General Public License
#     as published by the Free Software Foundation; either version 2
#     of the License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program; if not, write to the Free Software
#     Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# Please consider donating to 1PLAPWDejJPJnY2ppYCgtw5ko8G5Q4hPzh if you
# want to support further development of the Modular Python Bitcoin Miner.



##############
# Work queue #
##############



import time
from threading import Condition, RLock, Thread



class WorkQueue(object):

  
  def __init__(self, core):
    self.core = core
    self.start_stop_lock = RLock()
    self.started = False
    # Initialize global work queue lock and wakeup condition
    self.lock = Condition()
    # Initialize job list container and count
    self.lists = {}
    self.count = 0
    self.expirycutoff = 0
    # Initialize taken job list and a lock for it
    self.takenlock = RLock()
    self.takenlists = {}
    
    
  def add_job(self, job):
    with self.lock:
      if not job.worksource.blockchain.check_job(job): return
      expiry = int(job.expiry)
      if not expiry in self.lists: self.lists[expiry] = [job]
      else: self.lists[expiry].append(job)
      self.count += 1
      job.register()
      self.lock.notify_all()
    
    
  def remove_job(self, job):
    with self.lock:
      try:
        self.lists[int(job.expiry)].remove(job)
        self.count -= 1
      except: pass
      
      
  def flush_all_of_work_source(self, worksource):
    with self.lock:
      for list in self.lists:
        for job in list:
          if job.worksource == worksource:
            list.remove(job)
            self.count -= 1
            job.destroy()
      for list in self.takenlists:
        for job in list:
          if job.worksource == worksource:
            list.remove(job)
            job.cancel()
    
    
  def get_job(self, worker, expiry_min_ahead):
    with self.lock:
      job = self._get_job_internal(expiry_min_ahead)
      self.core.fetcher.wakeup()
      job.set_worker(worker)
      with self.takenlock:
        expiry = int(job.expiry)
        if not expiry in self.takenlists: self.takenlists[expiry] = [job]
        else: self.takenlists[expiry].append(job)
      return job


  def _get_job_internal(self, expiry_min_ahead):
    self.count -= 1
    while True:
      keys = sorted(self.lists.keys())
      min_expiry = time.time() + expiry_min_ahead
      # Look for a job that meets min_expiry as closely as possible
      for expiry in keys:
        if expiry <= min_expiry: continue
        list = self.lists[expiry]
        if not list: continue
        return list.pop(0)
      # If there was none, look for the job with the latest expiry
      keys.reverse()
      for expiry in keys:
        if expiry > min_expiry: continue
        list = self.lists[expiry]
        if not list: continue
        return list.pop(0)
      # There were no jobs at all => Wait for some to arrive
      self.core.fetcher.wakeup()
      self.lock.wait()

        
  def start(self):
    with self.start_stop_lock:
      if self.started: return
      self.lists = {}
      self.takenlists = {}
      self.count = 0
      self.expirycutoff = 0
      self.shutdown = False
      self.cleanupthread = Thread(None, self.cleanuploop, "workqueue_cleanup")
      self.cleanupthread.daemon = True
      self.cleanupthread.start()
      self.started = True
  
  
  def stop(self):
    with self.start_stop_lock:
      if not self.started: return
      self.shutdown = True
      self.cleanupthread.join(10)
      self.lists = {}
      self.takenlists = {}
      self.count = 0
      self.expirycutoff = 0
      self.started = False

    
  def cleanuploop(self):
    while not self.shutdown:
      now = time.time()
      with self.lock:
        keys = sorted(self.lists.keys())
        cutoff = now + 10
        for expiry in keys:
          if expiry > cutoff: break
          if expiry > self.expirycutoff and expiry <= cutoff: self.count -= len(self.lists[expiry])
          if expiry <= now:
            for job in self.lists[expiry]: job.destroy()
            del self.lists[expiry]
        self.expirycutoff = cutoff
      with self.takenlock:
        keys = sorted(self.takenlists.keys())
        for expiry in keys:
          if expiry <= now:
            for job in self.takenlists[expiry]: job.cancel()
            del self.takenlists[expiry]
      time.sleep(1)
