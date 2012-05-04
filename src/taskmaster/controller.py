"""
taskmaster.controller
~~~~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010 DISQUS.
:license: Apache License 2.0, see LICENSE for more details.
"""

import sys
import time
import cPickle as pickle
from os import path, unlink
from threading import Thread


class Controller(object):
    def __init__(self, server, target, state_file=None, progressbar=True):
        cls = type(self)

        if isinstance(target, basestring):
            target = cls.get_callable_target(target)

        if not state_file:
            target_file = sys.modules[target.__module__].__file__
            state_file = path.join(path.dirname(target_file),
                '%s.state' % (path.basename(target_file),))

        self.server = server
        self.target = target
        self.state_file = state_file
        if progressbar:
            self.pbar = cls.get_progressbar()
        else:
            self.pbar = None

    @classmethod
    def get_callable_target(cls, target):
        try:
            mod_path, func_name = target.split(':', 1)
        except ValueError:
            raise ValueError('target must be in form of `path.to.module:function_name`')

        module = __import__(mod_path, {}, {}, [func_name], -1)
        callback = getattr(module, func_name)

        return callback

    @classmethod
    def get_progressbar(cls):
        from taskmaster.progressbar import Counter, Speed, Timer, ProgressBar, UnknownLength

        widgets = ['Current Job: ', Counter(), ' | ', Speed(), ' | ', Timer()]

        pbar = ProgressBar(widgets=widgets, maxval=UnknownLength)

        return pbar

    def read_state(self):
        if path.exists(self.state_file):
            print "Reading previous state from %r" % self.state_file
            with open(self.state_file, 'r') as fp:
                try:
                    return pickle.load(fp)
                except Exception, e:
                    print "There was an error reading from state file. Ignoring and continuing without."
                    import traceback
                    traceback.print_exc()
                    print e
        return {}

    def update_state(self, job_id, job, fp=None):
        if job_id:
            data = {
                'job': job,
                'job_id': job_id,
            }
        else:
            data = {}
        if not fp:
            with open(self.state_file, 'w') as fp:
                pickle.dump(data, fp)
        else:
            fp.seek(0)
            pickle.dump(data, fp)

    def state_writer(self):
        last_job_id = None
        with open(self.state_file, 'w') as fp:
            while self.server.is_alive():
                time.sleep(0)
                try:
                    job_id, job = self.server.first_job()
                except IndexError:
                    continue

                if self.pbar:
                    self.pbar.update(job_id)

                if not job or job_id == last_job_id:
                    continue

                self.update_state(job_id, job, fp)

                last_job_id = job_id

    def reset(self):
        if path.exists(self.state_file):
            unlink(self.state_file)

    def start(self):
        kwargs = {}
        last_job = self.read_state()
        if last_job:
            kwargs['last'] = last_job['job']
            start_id = last_job['job_id']
        else:
            start_id = 0

        self.server.start()
        if self.pbar:
            self.pbar.start()

        state_writer = Thread(target=self.state_writer)
        state_writer.daemon = True
        state_writer.start()

        job_id, job = (None, None)
        for job_id, job in enumerate(self.target(**kwargs), start_id):
            self.server.put_job((job_id, job))
            time.sleep(0)

        while self.server.has_work():
            time.sleep(0)

        self.server.shutdown()
        state_writer.join(1)

        self.update_state(job_id, job)

        if self.pbar:
            self.pbar.finish()