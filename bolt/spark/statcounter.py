#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# This file is ported from spark/util/StatCounter.scala
#
# This code is based on pyspark's statcounter.py and used under the ASF 2.0 license.

import copy
import sys
from itertools import chain

from numpy import zeros, maximum, minimum, sqrt, isnan, fmin, fmax, shape, reshape, invert, amax, amin, nansum, dstack

if sys.version_info > (3,):
    long = int


class StatCounter(object):

    REQUIRED_FOR = {
        'mean': ('mu', 'n_n'),
        'sum': ('mu', 'n_n'),
        'variance': ('mu', 'm2', 'n_n'),
        'stdev': ('mu', 'n', 'm2', 'n_n'),
        'nanmean': ('mu_n', 'n_n'),
        'nansum': ('mu_n', 'n_n'),
        'nanvariance': ('mu_n', 'm2_n', 'n_n'),
        'nanstdev': ('mu_n', 'm2_n', 'n_n'),
        'nanmin': ('minValue_n', 'n_n'),
        'nanmax': ('maxValue_n', 'n_n'),
        'all': ('n', 'mu', 'm2', 'n_n', 'mu_n', 'm2_n')
    }

    def __init__(self, values=(), stats='all'):
        self.n = long(0)    # Running count of our values
        self.mu = 0.0  # Running mean of our values
        self.m2 = 0.0  # Running variance numerator (sum of (x - mean)^2)
        self.n_n = None    # Running count of our values without NaNs
        self.mu_n = None  # Running mean of our values without NaNs
        self.m2_n = None  # Running variance numerator (sum of (x - mean)^2) without NaNs
        self.maxValue_n = None
        self.minValue_n = None

        if isinstance(stats, basestring):
            stats = [stats]

        self.requiredAttrs = frozenset(chain().from_iterable([StatCounter.REQUIRED_FOR[stat] for stat in stats]))

        for v in values:
            self.merge(v)

    # add a value into this StatCounter, updating the statistics
    def merge(self, value):
        self.n += 1
        if self.__requires('mu'):
            delta = value - self.mu
            self.mu += delta / self.n
            if self.__requires('m2'):
                self.m2 += delta * (value - self.mu)

        if self.n_n is None:
            # Create the initial counter and set it to zeros
            self.n_n = zeros(value.shape)
            self.mu_n = zeros(value.shape)
            self.m2_n = zeros(value.shape)

        self.n_n += ~isnan(value)
        if self.__requires('mu_n'):
            delta = (value - self.mu_n).squeeze()
            if nansum(isnan(value)):
                delta[isnan(value)] = 0
            self.mu_n = nansum(dstack((self.mu_n, (delta / self.n_n))), axis=2)

            if self.__requires('m2_n'):
                # Since value can have nans - replace with zeros
                tmpVal = value;
                tmpVal[isnan(tmpVal)] = 0
                self.m2_n += delta * (tmpVal - self.mu_n).squeeze()
        if self.__requires('maxValue_n'):
            self.maxValue_n = fmax(self.maxValue_n, value) if not self.maxValue_n is None else value
        if self.__requires('minValue_n'):
            self.minValue_n = fmin(self.minValue_n, value) if not self.minValue_n is None else value

        return self

    # checks whether the passed attribute name is required to be updated in order to support the
    # statistics requested in self.requested
    def __requires(self, attrname):
        return attrname in self.requiredAttrs

    # merge another StatCounter into this one, adding up the statistics
    def combine(self, other):
        if not isinstance(other, StatCounter):
            raise Exception("Can only merge Statcounters!")

        if other is self:  # reference equality holds
            self.merge(copy.deepcopy(other))  # Avoid overwriting fields in a weird order
        else:
            # accumulator should only be updated if it's valid in both statcounters:
            self.requiredAttrs = set(self.requiredAttrs).intersection(set(other.requiredAttrs))

            if self.n == 0:
                self.n = other.n
                for attrname in ('mu', 'm2', 'n_n', 'mu_n', 'm2_n', 'maxValue_n', 'minValue_n'):
                    if self.__requires(attrname):
                        setattr(self, attrname, getattr(other, attrname))

            elif other.n != 0:
                if self.n_n is None:
                    # Create the initial counter and set it to zeros
                    self.n_n = zeros(other.shape)
                    self.mu_n = zeros(other.shape)
                    self.m2_n = zeros(other.shape)
                if self.__requires('mu'):
                    delta = other.mu - self.mu
                    if other.n * 10 < self.n:
                        self.mu = self.mu + (delta * other.n) / (self.n + other.n)
                    elif self.n * 10 < other.n:
                        self.mu = other.mu - (delta * self.n) / (self.n + other.n)
                    else:
                        self.mu = (self.mu * self.n + other.mu * other.n) / (self.n + other.n)

                    if self.__requires('m2'):
                        self.m2 += other.m2 + (delta * delta * self.n * other.n) / (self.n + other.n)

                self.n += other.n

                if self.__requires('mu_n'):
                    delta = other.mu_n - self.mu_n
                    self.mu_n = (self.mu_n * self.n_n + other.mu_n * other.n_n) / (self.n_n + other.n_n)

                    #Set areas with no data to zero
                    self.mu_n[isnan(self.mu_n)] = 0

                    if self.__requires('m2_n'):
                        tmpAdd = (delta * delta * self.n_n * other.n_n) / (self.n_n + other.n_n)
                        tmpAdd[isnan(tmpAdd)] = 0
                        self.m2_n += other.m2_n + tmpAdd.squeeze()

                if self.__requires('maxValue_n'):
                    self.maxValue_n = fmax(self.maxValue_n, other.maxValue_n)
                if self.__requires('minValue_n'):
                    self.minValue_n = fmin(self.minValue_n, other.minValue_n)

                self.n_n += other.n_n

        return self

    # Clone this StatCounter
    def copy(self):
        return copy.deepcopy(self)

    def __isavail(self, attrname):
        if not all(attr in self.requiredAttrs for attr in StatCounter.REQUIRED_FOR[attrname]):
            raise ValueError("'%s' stat not available, must be requested at "
                             "StatCounter instantiation" % attrname)

    def count(self):
        return self.n

    @property
    def mean(self):
        self.__isavail('mean')
        return self.mu

    @property
    def sum(self):
        self.__isavail('sum')
        return self.n * self.mu

    # Return the variance of the values.
    @property
    def variance(self):
        self.__isavail('variance')
        if self.n == 0:
            return float('nan')
        else:
            return self.m2 / self.n

    @property
    def stdev(self):
        self.__isavail('stdev')
        return sqrt(self.variance)

    def nancount(self):
        return self.n_n

    @property
    def nanmean(self):
        self.__isavail('nanmean')
        return self.mu_n.squeeze()

    @property
    def nansum(self):
        self.__isavail('nansum')
        return self.n_n * self.mu_n.squeeze()

    @property
    def nanmin(self):
        self.__isavail('nanmin')
        return self.minValue_n

    @property
    def nanmax(self):
        self.__isavail('nanmax')
        return self.maxValue_n

    # Return the variance of the values.
    @property
    def nanvariance(self):
        self.__isavail('nanvariance')
        tmpVar = self.m2_n / self.n_n
        # set areas with no data to zero
        mask = isnan(tmpVar)
        if nansum(mask):
            tmpVar[isnan(tmpVar)] = 0
        return tmpVar

    # Return the standard deviation of the values.
    @property
    def nanstdev(self):
        self.__isavail('nanstdev')
        return sqrt(self.nanvariance)

    def __repr__(self):
        return ("(count: %s, mean: %s, stdev: %s, required: %s, nancount: %s, nanmean: %s, nanstdev: %s, nanmin: %s, "
                "nanmax: %s)" %
                (self.count(), self.mean, self.stdev, str(tuple(self.requiredAttrs)), self.nancount(),
                 self.nanmean(), self.nanstdev, self.nanmin, self.nanmax))
