import torch
from models import knn
import torch.nn as nn
import models.functional as MF


class TransporterNet(knn.Container):
    def __init__(self,
                 feature_cnn,
                 keypoint_cnn,
                 key2map,
                 decoder,
                 init_weights=True,
                 combine_method='loop'):
        super().__init__()
        self.feature = feature_cnn
        self.keypoint = keypoint_cnn
        self.ssm = knn.SpatialLogSoftmax()
        self.key2map = key2map
        self.decoder = decoder
        self.combine_method = combine_method

        if init_weights:
            self._initialize_weights()

    def extract(self, x):
        phi = self.feature(x)
        heatmap = self.keypoint(x)
        k, p = self.ssm(heatmap, probs=True)
        m = self.key2map(k, height=phi.size(2), width=phi.size(3))
        return phi, heatmap, k, p, m

    def forward(self, xs, xt):

        with torch.no_grad():
            phi_xs, heatmap_xs, k_xs, p_xs, m_xs = self.extract(xs)

        phi_xt, heatmap_xt, k_xt, p_xt, m_xt = self.extract(xt)

        if self.combine_method == 'loop':
            for i in range(k_xt.size(1)):
                mask_xs = m_xs[:, i:i+1]
                mask_xt = m_xt[:, i:i+1]
                phi_xs = phi_xs * (1 - mask_xs) * (1 - mask_xt) + phi_xt * mask_xt

        elif self.combine_method == 'sum_and_clamp':
            mask_xs = torch.sum(m_xs, dim=1, keepdim=True).clamp(0.0, 1.0)
            mask_xt = torch.sum(m_xt, dim=1, keepdim=True).clamp(0.0, 1.0)
            phi_xs = phi_xs * (1 - mask_xs) * (1 - mask_xt) + phi_xt * mask_xt

        elif self.combine_method == 'pretrained_network':
            mask_xs = m_xs
            mask_xt = m_xt
            phi_xs = phi_xs * (1 - mask_xs) * (1 - mask_xt) + phi_xt * mask_xt

        elif self.combine_method == 'max':
            mask_xs, i = torch.max(m_xs, dim=1, keepdim=True)
            mask_xt, i = torch.max(m_xt, dim=1, keepdim=True)
            phi_xs = phi_xs * (1 - mask_xs) * (1 - mask_xt) + phi_xt * mask_xt

        x_t = self.decoder(phi_xs)

        return x_t, phi_xs, k_xt, m_xt, p_xt, heatmap_xt, mask_xs, mask_xt

    def load(self, directory):
        self.feature.load(directory + '/encoder')
        self.keypoint.load(directory + '/keypoint')
        self.decoder.load(directory + '/decoder')

    def load_from_autoencoder(self, directory):
        self._initialize_weights()
        self.feature.load(directory + '/encoder', out_block=False)
        self.keypoint.load(directory + '/encoder', in_block=True, core=True, out_block=False)
        self.decoder.load(directory + '/decoder', in_block=False, core=True, out_block=True)

    def save(self, directory):
        self.feature.save(directory + '/encoder')
        self.keypoint.save(directory + '/keypoint')
        self.decoder.save(directory + '/decoder')


class MaskMaker(nn.Module):
    """  uses a pretrained convolutions to make a mask from keypoints """
    def __init__(self, map_f):
        super().__init__()
        self.map = map_f

    def __call__(self, k, height, width):
        with torch.no_grad():
            m = MF.point_map(k, height, width)
            return self.map(m)


class TransporterMap(knn.Container):
    def __init__(self, mapper, init_weights=True):
        super().__init__()
        self.map = mapper
        if init_weights:
            self._initialize_weights()

    def forward(self, x):
        return self.map(x)

    def load(self, directory):
        self.map.load(directory + '/map')

    def save(self, directory):
        self.map.save(directory + '/map')