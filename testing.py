import argparse
import numpy as np
import torch
from torch.utils.data import DataLoader
import torch.optim as optim
import os

import matplotlib
matplotlib.use('agg')  # use matplotlib without GUI support
import matplotlib.pyplot as plt

from lib.models.unet import UNet
from lib.datasets.ibims import Ibims

from lib.utils.net_utils import load_checkpoint
from lib.utils.evaluate_ibims_error_metrics import compute_global_errors, \
    compute_depth_boundary_error, compute_directed_depth_error

# =================PARAMETERS=============================== #
parser = argparse.ArgumentParser()

# network training procedure settings
parser.add_argument('--use_normal', action='store_true', help='whether to use rgb image as network input')
parser.add_argument('--use_occ', action='store_true', help='whether to use occlusion as network input')

parser.add_argument('--lr', type=float, default=0.0001, help='learning rate of optimizer')

# pth settings
parser.add_argument('--checkpoint', type=str, default=None, help='optional reload model path')
parser.add_argument('--result_dir', type=str, default='result', help='result folder')

# dataset settings
parser.add_argument('--val_dir', type=str, default='/space_sdd/ibims', help='testing dataset')
parser.add_argument('--val_method', type=str, default='junli')
parser.add_argument('--val_label_dir', type=str, default='contour_pred_connectivity8')
parser.add_argument('--val_label_ext', type=str, default='-rgb-order-pix.npy')

opt = parser.parse_args()
print(opt)
# ========================================================== #


# =================CREATE DATASET=========================== #
dataset_val = Ibims(opt.val_dir, opt.val_method, label_dir=opt.val_label_dir, label_ext=opt.val_label_ext)
val_loader = DataLoader(dataset_val, batch_size=1, shuffle=False)
# ========================================================== #


# ================CREATE NETWORK AND OPTIMIZER============== #
net = UNet(use_occ=opt.use_occ, use_normal=opt.use_normal)
optimizer = optim.Adam(net.parameters(), lr=opt.lr, weight_decay=0.0005)

load_checkpoint(net, optimizer, opt.checkpoint)

net.cuda()
# ========================================================== #


# ===================== DEFINE TEST ======================== #
def test(data_loader, net, result_dir):
    # Initialize global and geometric errors ...
    num_samples = len(data_loader)
    rms = np.zeros(num_samples, np.float32)
    log10 = np.zeros(num_samples, np.float32)
    abs_rel = np.zeros(num_samples, np.float32)
    sq_rel = np.zeros(num_samples, np.float32)
    thr1 = np.zeros(num_samples, np.float32)
    thr2 = np.zeros(num_samples, np.float32)
    thr3 = np.zeros(num_samples, np.float32)

    dbe_acc = np.zeros(num_samples, np.float32)
    dbe_com = np.zeros(num_samples, np.float32)

    dde_0 = np.zeros(num_samples, np.float32)
    dde_m = np.zeros(num_samples, np.float32)
    dde_p = np.zeros(num_samples, np.float32)

    net.eval()
    with torch.no_grad():
        for i, data in enumerate(data_loader):
            # load data and label
            depth_gt, depth_coarse, occlusion, edge, normal = data
            depth_gt, depth_coarse, occlusion, normal = depth_gt.cuda(), depth_coarse.cuda(), occlusion.cuda(), normal.cuda()

            # forward pass
            depth_pred = net(depth_coarse, occlusion, normal).clamp(1e-9)

            # mask out invalid depth values
            valid_mask = (depth_gt != 0).float()
            gt_valid = depth_gt * valid_mask
            pred_valid = depth_pred * valid_mask
            init_valid = depth_coarse * valid_mask

            # get numpy array from torch tensor
            gt = gt_valid.squeeze().cpu().numpy()
            pred = pred_valid.squeeze().cpu().numpy()
            init = init_valid.squeeze().cpu().numpy()
            edge = edge.numpy()

            gt_name = os.path.join(result_dir, '{:04}_gt.png'.format(i))
            pred_name = os.path.join(result_dir, '{:04}_refine.png'.format(i))
            init_name = os.path.join(result_dir, '{:04}_init.png'.format(i))
            pred_error_name = os.path.join(result_dir, '{:04}_refine_error.png'.format(i))
            init_error_name = os.path.join(result_dir, '{:04}_init_error.png'.format(i))
            plt.imsave(gt_name, gt)
            plt.imsave(pred_name, pred)
            plt.imsave(init_name, init)
            # plt.imsave(pred_error_name, gt - pred)
            # plt.imsave(init_error_name, gt - init)

            gt_vec = gt.flatten()
            pred_vec = pred.flatten()

            abs_rel[i], sq_rel[i], rms[i], log10[i], thr1[i], thr2[i], thr3[i] = compute_global_errors(gt_vec, pred_vec)
            dbe_acc[i], dbe_com[i], est_edges = compute_depth_boundary_error(edge, pred)
            dde_0[i], dde_m[i], dde_p[i] = compute_directed_depth_error(gt_vec, pred_vec, 3.0)

    return abs_rel, sq_rel, rms, log10, thr1, thr2, thr3, dbe_acc, dbe_com, dde_0, dde_m, dde_p
# ========================================================== #


# save refined depth predictions
session_name = os.path.basename(os.path.dirname(opt.checkpoint))
testing_mode = 'gt' if opt.val_label_dir == 'label' else 'pred'
result_dir = os.path.join(opt.result_dir, session_name, opt.val_method, testing_mode)
if not os.path.exists(result_dir):
    os.makedirs(result_dir)

abs_rel, sq_rel, rms, log10, thr1, thr2, thr3, dbe_acc, dbe_com, dde_0, dde_m, dde_p = test(val_loader, net, result_dir)
print('############ Global Error Metrics #################')
print('rel    = ',  np.nanmean(abs_rel))
print('log10  = ',  np.nanmean(log10))
print('rms    = ',  np.nanmean(rms))
print('thr1   = ',  np.nanmean(thr1))
print('thr2   = ',  np.nanmean(thr2))
print('thr3   = ',  np.nanmean(thr3))
print('############ Depth Boundary Error Metrics #################')
print('dbe_acc = ',  np.nanmean(dbe_acc))
print('dbe_com = ',  np.nanmean(dbe_com))
print('############ Directed Depth Error Metrics #################')
print('dde_0  = ',  np.nanmean(dde_0)*100.)
print('dde_m  = ',  np.nanmean(dde_m)*100.)
print('dde_p  = ',  np.nanmean(dde_p)*100.)


# log testing reults
logname = os.path.join(result_dir, 'testing_{}.txt'.format(testing_mode))
with open(logname, 'w') as f:
    f.write('############ Global Error Metrics #################\n')
    f.write('rel    =  {:.3f}\n'.format(np.nanmean(abs_rel)))
    f.write('log10  =  {:.3f}\n'.format(np.nanmean(log10)))
    f.write('rms    =  {:.3f}\n'.format(np.nanmean(rms)))
    f.write('thr1   =  {:.3f}\n'.format(np.nanmean(thr1)))
    f.write('thr2   =  {:.3f}\n'.format(np.nanmean(thr2)))
    f.write('thr3   =  {:.3f}\n'.format(np.nanmean(thr3)))
    f.write('############ Depth Boundary Error Metrics #################\n')
    f.write('dbe_acc = {:.3f}\n'.format(np.nanmean(dbe_acc)))
    f.write('dbe_com = {:.3f}\n'.format(np.nanmean(dbe_com)))
    f.write('############ Directed Depth Error Metrics #################\n')
    f.write('dde_0  = {:.3f}\n'.format(np.nanmean(dde_0) * 100.))
    f.write('dde_m  = {:.3f}\n'.format(np.nanmean(dde_m) * 100.))
    f.write('dde_p  = {:.3f}\n\n'.format(np.nanmean(dde_p) * 100.))
