# -*- coding: utf-8 -*-

from game import Game
import random
from chainer import Chain, Variable, optimizers, cuda
import chainer.functions as F
import chainer.links     as L
import numpy             as np
from collections import deque
import chainer.serializers as S
import os.path
import time

class QNetwork(Chain):
    def __init__(self):
        super(QNetwork, self).__init__(
            l1=F.Linear(None, 512),
            l2=F.Linear(512, 256),
            l3=F.Linear(256, 3))

    def __call__(self, state):
        h1 = F.relu(self.l1(state))
        h2 = F.relu(self.l2(h1))
        h3 = self.l3(h2)
        return h3

class Conv1QNetwork(Chain):
    def __init__(self):
        super(Conv1QNetwork, self).__init__(
            conv1=F.Convolution2D(3, 32, ksize=(1, 10), pad=0),
            l1=F.Linear(960, 256),
            l2=F.Linear(256, 3))

    def __call__(self, state):
        h1 = F.relu(self.conv1(state))
        h4 = F.relu(self.l1(h1))
        h5 = self.l2(h4)
        return h5

class Conv2QNetwork(Chain):
    def __init__(self):
        super(Conv2QNetwork, self).__init__(
            conv1=F.Convolution2D(3,  16, ksize=(1, 10), pad=0),
            conv2=F.Convolution2D(16, 32, ksize=(3, 1),  pad=0),
            l1=F.Linear(832, 256),
            l2=F.Linear(256, 3))

    def __call__(self, state):
        h1 = F.relu(self.conv1(state))
        h2 = F.relu(self.conv2(h1))
        h4 = F.relu(self.l1(h2))
        h5 = self.l2(h4)
        return h5

class Conv3QNetwork(Chain):
    def __init__(self):
        super(Conv3QNetwork, self).__init__(
            conv1=F.Convolution2D(3, 32, ksize=(1, 10), pad=0),
            l1=F.Linear(960, 512),
            l2=F.Linear(512, 256),
            l3=F.Linear(256, 128),
            l4=F.Linear(128, 3))

    def __call__(self, state):
        h1 = F.relu(self.conv1(state))
        h2 = F.relu(self.l1(h1))
        h3 = F.relu(self.l2(h2))
        h4 = F.relu(self.l3(h3))
        h5 = self.l4(h4)
        return h5

class AtariQNetwork(Chain):
    def __init__(self):
        super(AtariQNetwork, self).__init__(
            conv1=F.Convolution2D(3,  16, ksize=4, stride=2),
            conv2=F.Convolution2D(16, 32, ksize=2, stride=1),
            l1=F.Linear(None, 256),
            l2=F.Linear(256, 3))

    def __call__(self, state):
        h1 = F.relu(self.conv1(state))
        h2 = F.relu(self.conv2(h1))
        h4 = F.relu(self.l1(h2))
        h5 = self.l2(h4)
        return h5

class Average(object):
    def __init__(self, size):
        self.__size = size
        self.__sum_value = 0.0
        self.__average_value = 0.0
        self.__value_count = 0
        self.__values = deque()
        self.__history = []

    def add(self, value):
        if self.__value_count < self.__size:
            self.__value_count += 1
        else:
            self.__sum_value -= self.__values.popleft()
        self.__sum_value += value
        self.__average_value = self.__sum_value / self.__value_count
        self.__values.append(value)
        self.__history.append(self.__average_value)

    def average(self):
        return self.__average_value

    def history(self):
        return self.__history

class AiController(object):
    OBSERVE_FRAME = 3200
    REPLAY_MEMORY = 50000
    BATCH = 32
    GAMMA = 0.5

    INITIAL_EPSILON = 0.3
    FINAL_EPSILON = 0.01
    EXPLORELATION_FRAME = 1000000

    def __init__(self, game, player, args):
        self.__with_train = args.mode == 'train'
        self.__verbose    = args.output == 'game'
        self.__policy     = args.strategy
        self.__save_file  = args.file

        self.__game       = game
        self.__player     = player
        self.__frametime  = time.time()

        if args.network == "normal":
            self.__network = QNetwork()
        if args.network == "conv1":
            self.__network = Conv1QNetwork()
        if args.network == "conv2":
            self.__network = Conv2QNetwork()
        if args.network == "conv3":
            self.__network = Conv3QNetwork()
        if args.network == "atari":
            self.__network = AtariQNetwork()

        if args.gpu >= 0:
            device = cuda.get_device(int(args.gpu))
            device.use()
            self.__network.to_gpu()
            print('GPU MODE: {0}'.format(device))

        self.xp = self.__network.xp

        self.__optimizer = optimizers.Adam()
        self.__optimizer.setup(self.__network)

        self.__timestamp = 0
        self.__point = 0.0

        self.__history = deque()
        self.loss_average = Average(1000)

        self.__train_inputs = self.__network.xp.zeros((AiController.BATCH, 3, Game.DISPLAY_HEIGHT, Game.DISPLAY_WIDTH))
        self.__train_targets = self.__network.xp.zeros((AiController.BATCH, 3))
        self.__state_cache = []
        for _ in range(0, 3):
            a = []
            self.__state_cache.append(a)
            for _ in range(0, Game.DISPLAY_HEIGHT):
                b = []
                a.append(b)
                for _ in range(0, Game.DISPLAY_WIDTH):
                    b.append(0.0)

        self.epsilon = AiController.INITIAL_EPSILON
        self.load()

    def log(self, str):
        if self.__verbose:
            print(str)

    def save(self):
        if self.__save_file is None:
            return
        S.save_hdf5(self.__save_file, self.__network)

    def load(self):
        if self.__save_file is None:
            return
        if os.path.isfile(self.__save_file):
            print('loaded model!')
            S.load_hdf5(self.__save_file, self.__network)

    def get_display_as_state(self):
        state = self.__state_cache
        display = self.__game.current_display()
        for i in range(0, len(display)):
            for j in range(0, len(display[i])):
                for x in state:
                    x[i][j] = 0.0
        for i in range(0, len(display)):
            for j in range(0, len(display[i])):
                point = display[i][j]
                if point is not None:
                    state[point.state_index()][i][j] += 1.0
        return state

    def print_state(self, state):
        for channel in state:
            print('=========')
            for row in channel:
                print(row)

    def current_state(self):
        state = self.xp.asarray([self.get_display_as_state()])
        state = state.astype(self.xp.float32)
        return state

    def asarray(self, x):
        return self.__network.xp.asarray(x)

    def random_history(self, size):
        return random.sample(self.__history, AiController.BATCH)

    def push_history(self, step_data):
        self.__history.append(step_data)
        if len(self.__history) > AiController.REPLAY_MEMORY:
            self.__history.popleft()

    def next(self):
        state = self.asarray(self.current_state())
        q_value = self.__network(state)
        print('Q Value: {}'.format(q_value.data))

        if self.__policy == 'greedy':
            action = self.xp.argmax(q_value.data.reshape(-1))
            self.log("GREEDY: {}".format(action))
        elif self.__policy == 'egreedy':
            if random.random() <= self.epsilon:
                action = random.randint(0, 2)
                self.log("ε-greedy RANDOM: {}".format(action))
            else:
                _q_value_data = q_value.data.reshape(-1)
                action = self.xp.argmax(_q_value_data)
                self.log("ε-greedy GREEDY: {}".format(action))
        elif self.__policy == 'softmax':
            q_value_soft = F.softmax(q_value / 0.1)
            prob = q_value_soft.data.reshape(-1)
            action = np.random.choice(len(prob), p=prob)
            self.log("Q: {}, SOFTMAX: {}".format(q_value.data, q_value_soft.data))

        if self.epsilon > AiController.FINAL_EPSILON and self.__timestamp >  AiController.OBSERVE_FRAME:
            self.epsilon -= (AiController.INITIAL_EPSILON - AiController.FINAL_EPSILON) / float(AiController.EXPLORELATION_FRAME)

        if action == 0:
            self.__player.move_left()
        elif action == 1:
            self.__player.move_right()
        elif action == 2:
            self.__player.shoot_bullet()

        prev_point = self.__game.total_point()

        ###################################################################################
        self.__game.update()
        self.__timestamp += 1
        ###################################################################################

        if not self.__with_train:
            frametime = time.time()
            while frametime - self.__frametime < 0.1:
                frametime = time.time()
            self.__frametime = frametime

        curr_point = self.__game.total_point() - prev_point
        self.__point = self.__point * AiController.GAMMA + (curr_point / 100.0)

        self.log("TIME: {}, GAME SCORE: {}".format(self.__timestamp, self.__point))

        reward = (curr_point) / 100.0
        state_prime = self.current_state()

        self.push_history({
            "state": state,
            "action": action,
            "reward": reward,
            "state_prime": state_prime,
        })

        if self.__with_train and self.__timestamp > AiController.OBSERVE_FRAME:
            minibatch = self.random_history(AiController.BATCH)

            for i in range(0, len(minibatch)):
                data = minibatch[i]
                state = data['state']
                action = int(data['action'])
                reward = data['reward']
                state_prime = data['state_prime']

                Q_value = self.__network(state)
                Q_sa = self.__network(state_prime)
                self.__train_inputs[i : i + 1] = state
                self.__train_targets[i] = Q_value.data
                self.__train_targets[i, action] = reward + AiController.GAMMA * self.xp.max(Q_sa.data)

            x = self.__network(self.__train_inputs.astype(self.xp.float32))
            t = self.__train_targets.astype(self.xp.float32)
            loss = F.mean_squared_error(x, t)
            self.__optimizer.update(lambda: loss)
            self.loss_average.add(loss.data)
            print('LOSS: {}'.format(loss.data))
            print("Average LOSS: {}".format(self.loss_average.average()))

            if self.__timestamp % 10000 == 0:
                self.log('save model!')
                self.save()

