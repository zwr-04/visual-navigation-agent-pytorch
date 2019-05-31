import torch.multiprocessing as mp
from queue import Empty

from tensorboardX import SummaryWriter
class SummaryThread(mp.Process):
    def __init__(self,
                input_queue : mp.Queue):
        super(SummaryThread, self).__init__()
        self.i_queue = input_queue
        self.exit = mp.Event()

    def run(self):
        print("SummaryThread starting")
        self.writer = SummaryWriter()
        while True and not self.exit.is_set():
            try:
                name, scalar, step = self.i_queue.get(timeout=1)
                self.writer.add_scalar(name, scalar, step)
            except Empty:
                pass
        print("Exiting SummaryThread")
    def stop(self):
        print("Stop initiated for SummaryThread")
        self.exit.set()
