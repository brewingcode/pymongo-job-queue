import pymongo
from datetime import datetime
import time


class JobQueue:

    # Capped collection documents can not have its size updated
    # https://docs.mongodb.com/manual/core/capped-collections/#document-size
    DONE = 'done'.ljust(10, '_')
    WAITING = 'waiting'.ljust(10, '_')
    WORKING = 'working'.ljust(10, '_')

    def __init__(self, db, silent=False, iterator_wait=None):
        """ Return an instance of a JobQueue.
        Initialization requires one argument, the database,
        since we use one jobqueue collection to cover all
        sites in an installation/database. The second
        argument specifies if to print status while waiting
        for new job, the default value is False"""
        self.db = db
        if not self._exists():
            print ('Creating jobqueue collection.')
            self._create()
        self.q = self.db['jobqueue']
        self.iterator_wait = iterator_wait
        if self.iterator_wait is None:
            def deafult_iterator_wait():
                time.sleep(5)
                if not silent:
                    print ('waiting!')
                return True

            self.iterator_wait = deafult_iterator_wait

    def _create(self, capped=True):
        """ Creates a Capped Collection. """
        # TODO - does the size parameter mean number of docs or bytesize?
        try:
            self.db.create_collection('jobqueue',
                                      capped=capped, max=100000,
                                      size=100000, autoIndexId=True)
        except:
            raise Exception('Collection "jobqueue" already created')

    def _find_opts(self):
        if hasattr(pymongo, 'CursorType'):
            return {'cursor_type': pymongo.CursorType.TAILABLE_AWAIT}   # pylint: disable=no-member
        return {'Tailable': True}

    def _exists(self):
        """ Ensures that the jobqueue collection exists in the DB. """
        return 'jobqueue' in self.db.collection_names()

    def valid(self):
        """ Checks to see if the jobqueue is a capped collection. """
        opts = self.db['jobqueue'].options()
        if opts.get('capped', False):
            return True
        return False

    def next(self):
        """ Runs the next job in the queue. """
        row = self.q.find_one_and_update({'status': self.WAITING},
                                         {'$set':
                                            {'status': self.DONE,
                                             'ts.started': datetime.utcnow(),
                                             'ts.done': datetime.utcnow()}})
        if row:
            return row
        raise Exception('There are no jobs in the queue')

    def pub(self, data=None):
        """ Publishes a doc to the work queue. """
        doc = dict(
            ts={'created': datetime.now(),
                'started': datetime.now(),
                'done': datetime.now()},
            status=self.WAITING,
            data=data)
        try:
            self.q.insert(doc, manipulate=False)
        except:
            raise Exception('could not add to queue')
        return True

    def __iter__(self):
        """ Iterates through all docs in the queue
            andw aits for new jobs when queue is empty. """
        get_next = True
        while get_next:
            try:
                row = self.q.find_one_and_update(
                    {'status': self.WAITING},
                    {'$set':
                     {'status': self.WORKING,
                      'ts.started': datetime.now()}})
                if row is None:
                    raise Exception('There are no jobs in the queue')
                print('---')
                print('Working on job:')
                yield row
                self.q.update_one({'_id': row['_id']},
                                  {'$set': {'status': self.DONE,
                                            'ts.done': datetime.utcnow()}})
            except:
                get_next = self.iterator_wait()

    def queue_count(self):
        """ Returns the number of jobs waiting in the queue. """
        cursor = self.q.find({'status': self.WAITING})
        if cursor:
            return cursor.count()

    def clear_queue(self):
        """ Drops the queue collection. """
        self.q.drop()
