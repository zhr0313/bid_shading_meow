# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import multiprocessing
import threading
import json
import time
import os
import sys
import logging
from kconf.get_config import get_json_config
from kconf.client import update_config
from kconf.exception import KConfError
from datetime import datetime

# +
class MEOW:
    def __init__(self, M0, V, P, K, sigma, eta, T1, T2, N1, N2):
        self.M0 = M0  # number of bins M0
        self.V = V  # ranges
        self.P = P  # 最大出价价格
        self.K = K  # number of prices  每个私人价值分桶下候选出价价格的数量
        self.sigma = sigma  # discount factor
        self.eta = eta  # learning rate
        self.T1 = T1  # update period
        self.T2 = T2
        self.N1 = N1  # threshold
        self.N2 = N2
        self.b_p = []
        

        self.bins = self.initialize_bins()

    def initialize_bins(self):
        bins = []
        bin_width = self.V / self.M0
        for i in range(self.M0):
            bin_low = i * bin_width
            bin_high = (i + 1) * bin_width
            bin_data = {
                'v_low': bin_low,
                'v_high': bin_high,
                'count': 0,
                'price': [(j) * self.P / self.K for j in range(self.K)],
                'history': np.zeros(self.K)
            }

            bins.append(bin_data)
        return bins

    def search_current_bin(self, v):
        for bin_data in self.bins:
            if bin_data['v_low'] <= v < bin_data['v_high']:
                return bin_data
        if v >= self.V:
        # if v > self.bins[-1]['v_high']:
            new_bin = {
                'v_low': v,
                'v_high': v + 1,
                'count': 0,
                'price': [(j) * self.P / self.K for j in range(self.K)],
                'history': np.zeros(self.K)
            }
            self.bins.append(new_bin)
            return new_bin

    # def exponential_weighting(self, bin_data):
    #     prob = np.exp(self.eta * bin_data['history'])  # 溢出！
    #     prob /= np.sum(prob) # 归一化
    #     return np.random.choice(bin_data['price'], p=prob)

    def softmax(self, x):
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum(axis=0)

    def exponential_weighting(self, bin_data):
        prob = self.softmax(self.eta * bin_data['history'])
        return np.random.choice(bin_data['price'], p=prob)

    def update_bin(self, bin_data, v, m):
        for j in range(self.K):
            bin_data['history'][j] += self.instantreward(bin_data['price'][j], v, m)
        bin_data['count'] += 1

#     def instantreward(self, b, v, m):
#         if b > m:
#             if v > b:
#                 return v - b
#             else:
#                 return 1.5 * v -b
#         else:
#             return 0
    def instantreward(self, b, v, m):
        if b > m:
            return v-b
        else:
            return 0
#     def instantreward(self, b, v, m):
#         if b > m:
#             return v-b
#         else:
#             return -0.6*v
#     def instantreward(self, b, v, m):
#         if b > m:
#             return np.exp(m - b)
#         else:
#             return 0

    def split_or_merge_bins(self):
        new_bins = []
        i = 0
        while i < len(self.bins):
            bin_data = self.bins[i]
            # split a large bin into two smaller bins
            if bin_data['count'] >= self.N1:
                bin_data['history'] /= 2
                bin_data['count'] /= 2
                new_bin_l = {
                    'v_low': bin_data['v_low'],
                    'v_high': (bin_data['v_low'] + bin_data['v_high']) / 2,
                    'count': bin_data['count'],
                    'price': bin_data['price'],
                    'history': bin_data['history']
                }
                new_bin_r = {
                    'v_low': new_bin_l['v_high'],
                    'v_high': bin_data['v_high'],
                    'count': bin_data['count'],
                    'price': bin_data['price'],
                    'history': bin_data['history']
                }
                new_bins.append(new_bin_l)
                new_bins.append(new_bin_r)
                
            # merge two smaller bins into a large bin
            elif bin_data['count'] <= self.N2:
                # 处理bins里只有bin_data的情况
                # if len(self.bins) > 1:
                # neighbor_bin = min(self.bins, key = lambda x: x['count'] if x != bin_data else float('inf'))
                neighbor_bin = self.find_smaller_neigbor_bin(i, bin_data)
                if neighbor_bin is not None:
                    new_bin = {
                        'v_low': min(bin_data['v_low'], neighbor_bin['v_low']),
                        'v_high': max(bin_data['v_high'], neighbor_bin['v_high']),
                        'count': bin_data['count'] + neighbor_bin['count'],
                        'price': bin_data['price'],
                        'history': bin_data['history']
                    }

                    new_bins.append(new_bin)
                    i += 1
                else:
                    new_bins.append(bin_data)
            else:
                new_bins.append(bin_data)
            i += 1
        self.bins = sorted(new_bins, key=lambda x: x['v_low'])


    def find_smaller_neigbor_bin(self, i, bin_data):
        neighbor = None
        # if i - 1 >= 0:
        #     neighbor_left = self.bins[i - 1]
        #     if neighbor_left['count'] < bin_data['count']:
        #         neighbor = neighbor_left

        #只找右边
        if i + 1 < len(self.bins):
            neighbor_right = self.bins[i + 1]
            if neighbor_right['count'] <= bin_data['count']:   # <= v_low高的桶  count为0 导致后面没有合并
                neighbor = neighbor_right
        return neighbor

    def update_price_levels(self):
        def requantization():

            for bin_data in self.bins:
                j_star = np.argmax(bin_data['history'])
                j_min = max(j_star - 7, 0)
                j_max = min(j_star + 7, self.K - 1)
                new_price = [bin_data['price'][j_min] + j * (
                        bin_data['price'][j_max] - bin_data['price'][j_min]) / self.K for j in range(self.K)]
                bin_data['price'] = np.array(new_price)
                bin_data['history'] = np.zeros(self.K)

        requantization()
    
    def replace(self, bins, bin_data):
        for i, dict_item in enumerate(bins):
            if dict_item.get('v_low') == bin_data.get('v_low') and dict_item.get('v_high') == bin_data.get('v_high'):
                bins[i] = bin_data
                break
        
    
    def run(self, v_sequence, m_sequence):
        self.b_s = []
        for t, (v, m) in enumerate(zip(v_sequence, m_sequence), start=1):  # start = 1  生成索引从1开始
            try:
                bin_data = self.search_current_bin(v)
                self.bins = sorted(self.bins, key=lambda x: x['v_low'])

                b = self.exponential_weighting(bin_data)  # bid shading 后的出价
#                 self.b_s.append(b)

                self.update_bin(bin_data, v, m)

                if t % self.T1 == 0:
                    self.split_or_merge_bins()
                    # Discount
                    for bin_data in self.bins:
                        bin_data['count'] *= self.sigma
                        bin_data['history'] *= self.sigma

                if t % self.T2 == 0:

                    self.update_price_levels()
            except Exception as e:
                print(t, e)
                break
              
    def predict_single(self, v_sequence):
        try:
            for t, v in enumerate(v_sequence, start=1): 
                bin_data = self.search_current_bin(v)
                b = self.exponential_weighting(bin_data)  # bid shading 后的出价
                self.b_p.append(b)
        except Exception as e:
            print(t, e)



    

   
