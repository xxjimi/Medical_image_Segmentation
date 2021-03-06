import os
import torch
import adabound
from pylab import *
import numpy as np
import torch.nn as nn
from model import UNet
import SimpleITK as sitk
from numpy import ndarray
from scipy import ndimage
import torch.optim as optim
import matplotlib.pyplot as plt
import torch.nn.functional as F
from torchvision import transforms
from cross_validation import k_folds
from data import SegThorDataset, Rescale, ToTensor, Normalize, ToTensor2
#from result_submission import SegThorSubmission, Rescale, ToTensor, Normalize


def tensor_to_numpy(tensor):
    t_numpy = tensor.detach().cpu().numpy()
    t_numpy = np.transpose(t_numpy, [0, 2, 3, 1])
    t_numpy = np.squeeze(t_numpy)

    return t_numpy


# Trying to implement He weight initialization for function ReLu
def weight_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv2d') != -1:
        nn.init.kaiming_normal_(m.weight)
    elif classname.find('BatchNorm2d') != -1:
        nn.init.constant_(m.weight, 1)
        nn.init.constant_(m.bias, 0)
    elif classname.find('ConvTranspose2d') != -1:
        nn.init.kaiming_normal_(m.weight)
            
            
def dice_loss(result, target, total_classes = 5):
    
    """
    Pred: tensor with first dimension as batch
    target: tensor with first dimension as batch
    
    """

    epsilon = 1e-6
    total_loss = 0.0     
    dice_per_class = 0.0
    loss_label =  np.zeros(5)
    weight = [0.2, 2, 0.4, 0.9, 0.8]

    for i in range(result.size(0)):
        Loss = []

        for j in range(0, total_classes):
            result_square_sum = torch.sum(result[i, j, :, :])
            target_square_sum = torch.sum((target[i, :, :, :] == j))
            intersect = torch.sum(result[i, j, :, :] * (target[i, :, :, :] == j).float())
            dice = (2 * intersect + epsilon) / (result_square_sum + target_square_sum + intersect + epsilon)
            dice_per_class = 1 - dice
            total_loss += dice_per_class/total_classes
            loss_label[j] += dice_per_class

    loss_label = np.true_divide(loss_label, result.size(0))
    return loss_label, total_loss/result.size(0) 


def dice_loss2(result, target, total_classes = 5):

    """
    Pred: tensor with first dimension as batch
    target: tensor with first dimension as batch

    """
    epsilon = 1e-6
    total_loss = 0
    loss_label =  np.zeros(5)
    for j in range(0, total_classes):
            result_square_sum = torch.sum(result[:, j, :, :])
            target_square_sum = torch.sum(target[:, j, :, :])
            intersect = torch.sum(result[:, j, :, :] * (target[:, j, :, :]).float())
            dice = (2 * intersect + epsilon) / (result_square_sum + target_square_sum + intersect + epsilon)
            dice_loss_per_class = 1 - dice
            total_loss += dice_loss_per_class
            loss_label[j] += dice_loss_per_class

    total_loss /= total_classes
    total_loss /= result.size(0)
    loss_label = np.true_divide(loss_label, result.size(0))

    return total_loss, loss_label


def dice_loss3(result, target, coarse_segmentation, batch_size, total_classes = 5):
    
    epsilon = 1e-6
    target = target.view(batch_size, total_classes, -1).float()
    result = result.view(batch_size, total_classes, -1)

    numerator = 2 * torch.sum(result * target, 2)
    denominator = torch.sum(result + target**2, 2) + epsilon

    dice = 1 - torch.mean(numerator / denominator) 
    
    return dice


def main(epochs, batch_size, learning_rate):

    total_train_loss = 0
    total_val_loss = 0
    train_loss_seg =  np.zeros(5)
    val_loss_seg =  np.zeros(5)

    for train_list, test_list in k_folds(n_splits = 4, subjects = 41):
        # Loading train data
        train_loader = torch.utils.data.DataLoader(
            SegThorDataset("/home/WIN-UNI-DUE/smnemada/Master_Thesis/SegThor/data_sub/train_cv", phase='train',
                       transform=transforms.Compose([
                           Rescale(1.0),
                           Normalize(),
                           ToTensor2()
                       ]), file_list=train_list),
            batch_size=batch_size, shuffle=False)

        # Loading validation data
        val_set = SegThorDataset("/home/WIN-UNI-DUE/smnemada/Master_Thesis/SegThor/data_sub/train_cv", phase='val',
                                   transform=transforms.Compose([
                                       Rescale(1.0),
                                       Normalize(),
                                       ToTensor2()
                                   ]), file_list=test_list)

        val_loader = torch.utils.data.DataLoader(dataset=val_set,
                                             batch_size=1,
                                             shuffle=False)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = UNet().to(device)
        model.apply(weight_init)
        #optimizer = optim.Adam(model.parameters(), lr=learning_rate)    #learning rate to 0.001 for initial stage
        optimizer = optim.SGD(model.parameters(), lr = 0.01, momentum = 0.9, weight_decay = 0.00001)
        #optimizer = adabound.AdaBound(params = model.parameters(), lr = 0.001, final_lr = 0.1)

        for epoch in range(epochs):
            print('Epoch {}/{}'.format(epoch + 1, epochs))
            print('-' * 10)

            train_loss, train_loss_label = train(train_loader, model, optimizer, epoch, device, batch_size, train_list)
            val_loss, val_loss_label = validation(val_loader, model, epoch, device, batch_size, test_list)

            if val_loss < train_loss:
                os.makedirs("models", exist_ok=True)
                torch.save(model, "models/model.pt")

                # Save model output
                #save_results(epoch, device)

            if epoch%4==0:
                os.makedirs("models", exist_ok=True)
                torch.save(model, "models/model.pt")

            total_train_loss = total_train_loss + train_loss
            total_val_loss = total_val_loss + val_loss
            train_loss_seg = train_loss_seg + train_loss_label
            val_loss_seg = val_loss_seg + val_loss_label
            #evaluate_model(epoch, device)

    train_loss_seg = np.true_divide(train_loss_seg, 4)
    val_loss_seg = np.true_divide(val_loss_seg, 4)

    print(" Training Loss: ")
    print(total_train_loss // epochs)
    print("Background = {:.4f} Eusophagus = {:.4f}  Heart = {:.4f}  Trachea = {:.4f}  Aorta = {:.4f}\n".format(train_loss_seg[0], train_loss_seg[1], train_loss_seg[2], train_loss_seg[3], train_loss_seg[4]))

    print(" Validation Loss: ")
    print(total_val_loss // epochs)
    print("Background = {:.4f} Eusophagus = {:.4f}  Heart = {:.4f}  Trachea = {:.4f}  Aorta = {:.4f}\n".format(val_loss_seg[0], val_loss_seg[1], val_loss_seg[2], val_loss_seg[3], val_loss_seg[4]))


def train(train_loader, model, optimizer, epoch, device, batch_size, train_list):
    model.train()
    running_loss = 0.0
    loss_seg =  np.zeros(5)
    for batch_idx, sample in enumerate(train_loader):
        train_data, labels = sample['image'].to(device, dtype=torch.float), sample['label'].to(device, dtype=torch.uint8)

        optimizer.zero_grad()
        output = model(train_data)

        loss,loss_label = dice_loss2(output, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item()
        for i in range(5):
            loss_seg[i] += loss_label[i]


    epoch_loss = running_loss / len(train_loader)
    epoch_loss_class = np.true_divide(loss_seg, len(train_loader))

    print("Train")
    print("=====")
    print("Dice per class: Background = {:.4f} Eusophagus = {:.4f}  Heart = {:.4f}  Trachea = {:.4f}  Aorta = {:.4f}\n".format(epoch_loss_class[0], epoch_loss_class[1], epoch_loss_class[2], epoch_loss_class[3], epoch_loss_class[4]))
    print("Total Dice Loss: {:.4f}\n".format(epoch_loss))
    return epoch_loss, epoch_loss_class


def validation(val_loader, model, epoch, device, batch_size, test_list):
    model.eval()
    val_loss = 0.0
    loss_seg =  np.zeros(5)

    for batch_idx, sample in enumerate(val_loader):
        val_data, val_labels = sample['image'].to(device, dtype=torch.float), sample['label'].to(device, dtype=torch.uint8)
        with torch.no_grad():
            output = model(val_data)
            loss, loss_label = dice_loss2(output, val_labels)

        val_loss += loss.item()
        for i in range(5):
            loss_seg[i] += loss_label[i]

    epoch_loss_class = np.true_divide(loss_seg, len(val_loader))
    epoch_loss = val_loss / len(val_loader)
    print("Validation")
    print("==========")
    print("Dice per class: Background = {:.4f} Eusophagus = {:.4f}  Heart = {:.4f}  Trachea = {:.4f}  Aorta = {:.4f}\n".format(epoch_loss_class[0], epoch_loss_class[1], epoch_loss_class[2], epoch_loss_class[3], epoch_loss_class[4]))
    print("Total Dice Loss: {:.4f}\n".format(epoch_loss))

    return epoch_loss, epoch_loss_class


'''
def evaluate_model(epoch, device):

    model = torch.load("models/model.pt")
    model.eval()

    test_set = SegThorSubmission("/home/WIN-UNI-DUE/smnemada/Master_Thesis/SegThor/data_sub/test", patient = 'Patient_24.nii.gz', phase='test',
                                   transform=transforms.Compose([
                                       Rescale(1.0),
                                       Normalize(),
                                       ToTensor()
                                   ]))

    test_loader = torch.utils.data.DataLoader(dataset=test_set,
                                             batch_size=1,
                                             shuffle=False)


    count = 0
    seg_vol = zeros([len(test_set),  512, 512])
    with torch.no_grad():
        for batch_idx, (test_data, test_cs) in enumerate(test_loader):
            test_data, coarse_segmentation = test_data.to(device, dtype=torch.float), test_cs.to(device, dtype=torch.float)

            output = model(test_data, coarse_segmentation)

            max_idx = torch.argmax(output, 1, keepdim=True)
            max_idx = tensor_to_numpy(max_idx)

            slice_v = max_idx[:,:]
            #slice_v = slice_v.astype(float32)
            #slice_v = ndimage.interpolation.zoom(slice_v, zoom=2, order=0, mode='nearest', prefilter=True)
            seg_vol[count,:,:] = slice_v
            count = count + 1

        os.makedirs("validation_result", exist_ok=True)
        filename = os.path.join('validation_result', 'Patient_24_'+str(epoch)+'.nii')
        segmentation = sitk.GetImageFromArray(seg_vol, isVector=False)
        print("Saving segmented volume of size: ",segmentation.GetSize())
        sitk.WriteImage(sitk.Cast( segmentation, sitk.sitkUInt8 ), filename, True)
'''

if __name__ == "__main__":
    main(epochs=2, batch_size=20, learning_rate=0.001)
