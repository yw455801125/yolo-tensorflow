# -*- coding: utf8 -*-
# author: ronniecao
from __future__ import print_function
import sys
import os
import time
import pickle
import math
import numpy
import random
import matplotlib.pyplot as plt
import platform
import cv2
from threading import Thread

if 'Windows' in platform.platform():
    from queue import Queue
elif 'Linux' in platform.platform():
    from Queue import Queue


class ImageProcessor:
    
    def __init__(self, directory, image_size=288, max_objects_per_image=20, cell_size=7,
                 n_classes=1):
        # 参数赋值
        self.image_size = image_size
        self.max_objects = max_objects_per_image
        self.cell_size = cell_size
        self.n_classes = n_classes
        
        self.load_images_labels(directory)
    
    def load_images_labels(self, directory):
        if os.path.exists(directory):
            # 读取训练集
            train_file = os.path.join(directory, 'train.txt')
            self.load_dataset_loop(train_file, n_thread=5)
            
            # 读取验证集
            valid_file = os.path.join(directory, 'valid.txt')
            self.valid_images, self.valid_labels = \
                self.load_dataset_whole(valid_file, n_thread=5)
            self.n_valid = len(self.valid_images)
            
            # 读取测试集
            test_file = os.path.join(directory, 'test.txt')
            self.test_images, self.test_labels = \
                self.load_dataset_whole(test_file, n_thread=5)
            self.n_test = len(self.test_images)
            
            print('# of valid images: %d, # of test images %d' % (self.n_valid, self.n_test))
            print()
            sys.stdout.flush()
        
    def load_dataset_whole(self, filename, n_thread=10):
        # 读取训练集/验证集/测试集
        # 该函数使用多线程，将所有数据全部载入内存，不使用缓冲区
        
        info_list = Queue(maxsize=5000)
        dataset = Queue(maxsize=5000)
        
        # 读取info_list
        with open(filename, 'r') as fo:
            for line in fo:
                infos = line.strip().split(' ')
                info_list.put(infos)
        
        def _process(name):
            
            while not info_list.empty():
                
                infos = info_list.get()
                image_path = infos[0]
                label_infos = infos[1:]
                
                # 读取图像
                image = cv2.imread(image_path)
                [image_h, image_w, _] = image.shape
                
                # 处理 label
                i, n_objects = 0, 0
                label = [{}] * self.max_objects
                while i < len(label_infos) and n_objects < self.max_objects:
                    xmin = int(label_infos[i])
                    ymin = int(label_infos[i+1])
                    xmax = int(label_infos[i+2])
                    ymax = int(label_infos[i+3])
                    class_index = int(label_infos[i+4])
                    
                    left = max(0.0, 1.0 * xmin / image_w)
                    right = min(1.0 * xmax / image_w, 1.0)
                    top = max(0.0, 1.0 * ymin / image_h)
                    bottom = min(1.0 * ymax / image_h, 1.0)
                    
                    label[n_objects] = [left, right, top, bottom, class_index]
                    i += 5
                    n_objects += 1
                    
                dataset.put([image, label])
                
        # 以多线程的方式进行数据预处理
        thread_list = []
        for i in range(n_thread):
            thread = Thread(target=_process, args=(i,))
            thread_list.append(thread)
        for thread in thread_list:
            thread.start()
        for thread in thread_list:
            thread.join()
        
        # 处理dataset，将其分解成images和labels
        images, labels = [], []
        while not dataset.empty():
            image, label = dataset.get()
            images.append(image)
            labels.append(label)
        
        return images, labels
        
    def load_dataset_loop(self, filename, n_thread=10):
        # 读取训练集/验证集/测试集
        # 该函数使用多线程，基于生产者消费者模型
        # 生产者不停地读取原始数据，并且处理数据，并且存入循环队列中
        # 消费者从循环队列中读取batch后，直接传入模型进行训练
        
        info_list = []
        self.train_dataset = Queue(maxsize=10000)
        
        # 读取info_list
        with open(filename, 'r') as fo:
            for line in fo:
                infos = line.strip().split(' ')
                info_list.append(infos)
        
        def _produce(name):
            while True:
                random.shuffle(info_list)
                
                for infos in info_list:
                    image_path = infos[0]
                    label_infos = infos[1:]
                    
                    # 读取图像
                    image = cv2.imread(image_path)
                    [image_h, image_w, _] = image.shape
                    
                    # 处理 label
                    i, n_objects = 0, 0
                    label = [[0, 0, 0, 0, 0]] * self.max_objects
                    while i < len(label_infos) and n_objects < self.max_objects:
                        xmin = int(label_infos[i])
                        ymin = int(label_infos[i+1])
                        xmax = int(label_infos[i+2])
                        ymax = int(label_infos[i+3])
                        class_index = int(label_infos[i+4])
                    
                        left = max(0.0, 1.0 * xmin / image_w)
                        right = min(1.0 * xmax / image_w, 1.0)
                        top = max(0.0, 1.0 * ymin / image_h)
                        bottom = min(1.0 * ymax / image_h, 1.0)
                        
                        label[n_objects] = [left, right, top, bottom, class_index]
                        i += 5
                        n_objects += 1
                        
                    self.train_dataset.put([image, label])
                
        # 以多线程的方式进行数据预处理
        thread_list = []
        for i in range(n_thread):
            thread = Thread(target=_produce, args=(i,))
            thread_list.append(thread)
        for thread in thread_list:
            thread.start()
    
    def process_label(self, label):
        # true label and mask in 类别标记
        class_label = numpy.zeros(
            shape=(self.cell_size, self.cell_size, self.n_classes), 
            dtype='int32')
        class_mask = numpy.zeros(
            shape=(self.cell_size, self.cell_size),
            dtype='float32')
        
        # true_label and mask in 包围框标记
        box_label = numpy.zeros(
            shape=(self.max_objects, 6),
            dtype='float32')
        
        object_num = numpy.zeros(
            shape=(), dtype='int32')
        
        for j in range(self.max_objects):
            
            [left, right, top, bottom, class_index] = label[j]
            center_x = (left + right) / 2.0
            center_y = (top + bottom) / 2.0
            w = right - left
            h = bottom - top
            
            if class_index != 0:
                # 计算包围框标记
                center_cell_x = int(math.floor(self.cell_size * center_x))
                center_cell_y = int(math.floor(self.cell_size * center_y))
                box_label[j, :] = numpy.array(
                    [center_cell_x, center_cell_y, center_x, center_y, w, h])
                
                # 计算类别标记
                left_cell_x = max(
                    0, int(math.floor(self.cell_size * left)))
                right_cell_x = min(
                    int(math.floor(self.cell_size * right)), 
                    self.cell_size-1)
                top_cell_y = max(
                    0, int(math.floor(self.cell_size * top)))
                bottom_cell_y = min(
                    int(math.floor(self.cell_size * bottom)),
                    self.cell_size-1)
                
                for x in range(left_cell_x, right_cell_x+1):
                    for y in range(top_cell_y, bottom_cell_y+1):
                        _class_label = numpy.zeros(
                            shape=[self.n_classes,], dtype='int32')
                        _class_label[int(class_index)-1] = 1
                        class_label[y, x, :] = _class_label
                        class_mask[y, x] = 1.0
                
                # object_num增加
                object_num += 1
                            
        return class_label, class_mask, box_label, object_num
    
    def process_batch_labels(self, batch_labels):
        batch_class_labels, batch_class_masks, batch_box_labels, \
            batch_object_nums = [], [], [], []
            
        for i in range(len(batch_labels)):
            class_label, class_mask, box_label, object_num = self.process_label(batch_labels[i])
            batch_class_labels.append(class_label)
            batch_class_masks.append(class_mask)
            batch_box_labels.append(box_label)
            batch_object_nums.append(object_num)
        
        batch_class_labels = numpy.array(batch_class_labels, dtype='int32')
        batch_class_masks = numpy.array(batch_class_masks, dtype='float32')
        batch_box_labels = numpy.array(batch_box_labels, dtype='float32')
        batch_object_nums = numpy.array(batch_object_nums, dtype='int32')
        
        return batch_class_labels, batch_class_masks, batch_box_labels, batch_object_nums
        
    def _shuffle_datasets(self, images, labels):
        index = list(range(images.shape[0]))
        random.shuffle(index)
        
        return images[index], labels[index]
    
    def get_train_batch(self, batch_size):
        batch_images, batch_labels = [], []
            
        for i in range(batch_size):
            image, label = self.train_dataset.get()
            batch_images.append(image)
            batch_labels.append(label)
            
        return batch_images, batch_labels
            
    def get_valid_batch(self, i, batch_size):
        batch_images = self.valid_images[i: i+batch_size]
        batch_labels = self.valid_labels[i: i+batch_size]
        
        return batch_images, batch_labels
    
    def get_test_batch(self, i, batch_size):
        batch_images = self.test_images[i: i+batch_size]
        batch_labels = self.test_labels[i: i+batch_size]
        
        return batch_images, batch_labels
        
    def data_augmentation(self, images, labels,
                          mode='train', 
                          flip=False, 
                          crop=False, padding=20, 
                          whiten=False, 
                          noise=False, noise_mean=0, noise_std=0.01,
                          resize=False, jitter=0.2):
        # 图像尺寸变换
        if resize:
            images, labels = self.image_resize(images, labels, jitter=jitter, mode=mode)
        # 图像切割
        if crop:
            images = self.image_crop(images, padding=padding)
        # 图像翻转
        if flip:
            images, labels = self.image_flip(images, labels)
        # 图像白化
        if whiten:
            images = self.image_whitening(images)
        # 图像噪声
        if noise:
            images = self.image_noise(images, mean=noise_mean, std=noise_std)
            
        return numpy.array(images, dtype='uint8'), numpy.array(labels, dtype='float32')
    
    def image_crop(self, images, padding=20):
        # 图像切割
        new_images = []
        for i in range(images.shape[0]):
            old_image = images[i,:,:,:]
            old_image = numpy.lib.pad(
                old_image, ((padding, padding), (padding, padding), (0,0)),
                'constant', constant_values=((0, 0), (0, 0), (0, 0)))
            left = numpy.random.randint(int(padding*2))
            top = numpy.random.randint(int(padding*2))
            new_image = old_image[left: left+images.shape[1], top: top+images.shape[2], :]
            new_images.append(new_image)
        
        return numpy.array(new_images)
    
    def image_flip(self, images, labels):
        # 图像翻转
        for i in range(len(images)):
            old_image = images[i]
            if numpy.random.random() < 0.5:
                new_image = cv2.flip(old_image, 1)
            else:
                new_image = old_image
            images[i] = new_image
            
            # 重新计算box label
        for i in range(len(labels)):
            for j in range(len(labels[i])):
                if sum(labels[i][j]) == 0:
                    break
                right = 1.0 - labels[i][j][0]
                left = 1.0 - labels[i][j][1]
                labels[i][j][0] = left
                labels[i][j][1] = right
        
        return images, labels
    
    def image_whitening(self, images):
        # 图像白化
        for i in range(len(images)):
            old_image = images[i]
            new_image = (old_image - numpy.mean(old_image)) / numpy.std(old_image)
            images[i] = new_image
        
        return images
    
    def image_noise(self, images, mean=0, std=0.01):
        # 图像噪声
        for i in range(len(images)):
            old_image = images[i]
            new_image = old_image
            for i in range(image.shape[0]):
                for j in range(image.shape[1]):
                    for k in range(image.shape[2]):
                        new_image[i, j, k] += random.gauss(mean, std)
            images[i] = new_image
        
        return images
    
    def image_resize(self, images, labels, jitter=0.2, mode='train'):
        new_images, new_labels = [], []
        resized_w, resized_h = int(self.image_size), int(self.image_size)
        
        for i in range(len(images)):
            # 图像尺寸变换
            if mode == 'train':
                old_image = images[i]
                dw, dh = old_image.shape[1] * jitter, old_image.shape[0] * jitter
                
                new_ar = 1.0 * (old_image.shape[1] + random.randint(-int(dw), int(dw))) / \
                    (old_image.shape[0] + random.randint(-int(dh), int(dh)))
                scala = random.random() * (2 - 0.5) + 0.5
                
                # 新图像事原图像的scala的缩放，并使新图像的比例为new_ar
                if new_ar < 1:
                    nh = scala * resized_h
                    nw = nh * new_ar
                else:
                    nw = scala * resized_w
                    nh = nw / new_ar
                nw, nh = int(nw), int(nh)
                
                temp_image = cv2.resize(old_image, dsize=(nw, nh))
                
                if resized_w > nw:
                    dx = random.randint(0, resized_w - nw)
                    old_sx, old_ex = 0, nw
                    new_sx, new_ex = dx, dx + nw
                else:
                    dx = random.randint(0, nw - resized_w)
                    old_sx, old_ex = dx, dx + resized_w
                    new_sx, new_ex = 0, resized_w
                    
                if resized_h > nh:
                    dy = random.randint(0, resized_h - nh)
                    old_sy, old_ey = 0, nh
                    new_sy, new_ey = dy, dy + nh
                else:
                    dy = random.randint(0, nh - resized_h)
                    old_sy, old_ey = dy, dy + resized_h
                    new_sy, new_ey = 0, resized_h
                
                new_image = numpy.zeros(shape=(resized_h, resized_w, 3)) + 128
                new_image[new_sy: new_ey, new_sx: new_ex, :] = \
                    temp_image[old_sy: old_ey, old_sx: old_ex, :]
            
                new_images.append(new_image)
            
                # 重新计算labels
                new_label = [[0, 0, 0, 0, 0]] * self.max_objects
                n = 0
                for j in range(len(labels[i])):
                    if sum(labels[i][j]) == 0:
                        break
                    if mode == 'train':
                            
                        left = labels[i][j][0]
                        right = labels[i][j][1]
                        top = labels[i][j][2]
                        bottom = labels[i][j][3]
                            
                        if resized_w > nw:
                            new_left = (left * nw + dx) / resized_w
                            new_right = (right * nw + dx) / resized_w
                        else:
                            new_left = (left * nw - dx) / resized_w
                            new_right = (right * nw - dx) / resized_w
                            
                        if resized_h > nh:
                            new_top = (top * nh + dy) / resized_h
                            new_bottom = (bottom * nh + dy) / resized_h
                        else:
                            new_top = (top * nh - dy) / resized_h
                            new_bottom = (bottom * nh - dy) / resized_h
                            
                        new_left = min(max(0.0, new_left), 1.0 - 1e-6)
                        new_right = max(0.0, min(new_right, 1.0 - 1e-6))
                        new_top = min(max(0.0, new_top), 1.0 - 1e-6)
                        new_bottom = max(0.0, min(new_bottom, 1.0 - 1e-6))
                        
                        if new_right > new_left and new_bottom > new_top:
                            new_label[n] = [new_left, new_right, new_top, new_bottom, 
                                            labels[i][j][4]]
                            n += 1
                """
                cv2.imwrite('old.png', old_image)
                print(labels[i])
                cv2.imwrite('new.png', new_image)
                print(new_label)
                exit()
                """
                new_labels.append(new_label)
            else:
                old_image = images[i]
                new_image = cv2.resize(old_image, (self.image_size, self.image_size))
                new_images.append(new_image)
                new_labels.append(labels[i])
        
        return new_images, new_labels