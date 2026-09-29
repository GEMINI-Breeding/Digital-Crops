"""Dataset loading for paired YOLO-format image/label directories."""
import os
import numpy as np
import cv2


class Dataset:
    """A YOLO-format detection dataset: <root>/images and <root>/labels."""

    def __init__(self, root, name=None):
        self.root = root
        self.name = name or os.path.basename(root.rstrip('/'))
        self.img_dir = os.path.join(root, 'images')
        self.lbl_dir = os.path.join(root, 'labels')
        self.stems = sorted(
            os.path.splitext(f)[0] for f in os.listdir(self.img_dir)
            if f.lower().endswith(('.jpg', '.jpeg', '.png'))
        )
        self._img_ext = {
            os.path.splitext(f)[0]: os.path.splitext(f)[1]
            for f in os.listdir(self.img_dir)
        }

    def __len__(self):
        return len(self.stems)

    def image_path(self, stem):
        return os.path.join(self.img_dir, stem + self._img_ext[stem])

    def label_path(self, stem):
        return os.path.join(self.lbl_dir, stem + '.txt')

    def read_bgr(self, stem):
        im = cv2.imread(self.image_path(stem), cv2.IMREAD_COLOR)
        if im is None:
            raise IOError(f'could not decode {self.image_path(stem)}')
        return im

    def read_rgb(self, stem):
        return cv2.cvtColor(self.read_bgr(stem), cv2.COLOR_BGR2RGB)

    def boxes(self, stem):
        """Return (N,5) array of [cls, cx, cy, w, h] in normalized coords.

        Degenerate boxes (zero width or height) are dropped; the synthetic set
        contains a small number of these and they break log-aspect statistics.
        """
        p = self.label_path(stem)
        if not os.path.exists(p):
            return np.zeros((0, 5), np.float64)
        rows = []
        for line in open(p):
            f = line.split()
            if len(f) == 5:
                rows.append([float(x) for x in f])
        a = np.array(rows, np.float64).reshape(-1, 5)
        if len(a):
            a = a[(a[:, 3] > 0) & (a[:, 4] > 0)]
        return a

    def n_degenerate(self):
        n = 0
        for s in self.stems:
            p = self.label_path(s)
            if not os.path.exists(p):
                continue
            for line in open(p):
                f = line.split()
                if len(f) == 5 and (float(f[3]) <= 0 or float(f[4]) <= 0):
                    n += 1
        return n
