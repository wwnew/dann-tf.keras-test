
import tensorflow as tf
# tf.compat.v1.enable_eager_execution()
print(tf.__version__)
from tensorflow.keras.layers import Input, Dense, Dropout, Activation, Flatten, \
    Conv1D, BatchNormalization, MaxPooling1D, UpSampling1D
from tensorflow.python.keras.layers import Cropping1D
from tensorflow.keras.models import Model
from tensorflow.python.framework import ops
from tensorflow.keras.preprocessing import sequence
# I'm not sure of this import, most people import "Layer" just from Keras
from tensorflow.python.keras.engine.base_layer import Layer

import numpy as np
import pandas as pd
import re
import os
import glob


_model_name = 'lstm_model'


def autoencoder_model(timesteps, input_dim):
    inputs = Input(shape=(timesteps, input_dim), name='input')  # (,7813,6)
    activation = 'sigmoid'  # sigmoid
    activation_last = 'sigmoid'  # relu
    maxpoolsize = 2
    latent_dim = input_dim
    kernelsize = 8

    x = Conv1D(16, kernelsize, activation=activation, padding='same', use_bias=True)(inputs)
    x = BatchNormalization(axis=-1)(x)
    x = MaxPooling1D(maxpoolsize, padding='same')(x)
    x = Conv1D(latent_dim, kernelsize, activation=activation_last, padding='same', use_bias=True,
               input_shape=(timesteps, input_dim))(x)
    x = BatchNormalization(axis=-1)(x)
    encoded = MaxPooling1D(2, padding='same')(x)  # (,977,2)

    x = Conv1D(latent_dim, kernelsize, activation=activation, padding='same', use_bias=True,
               input_shape=(timesteps, input_dim))(encoded)
    x = BatchNormalization(axis=-1)(x)
    x = UpSampling1D(maxpoolsize)(x)
    x = Conv1D(16, kernelsize, activation=activation, padding='same', use_bias=True,
               input_shape=(timesteps, input_dim))(x)
    x = BatchNormalization(axis=-1)(x)
    x = UpSampling1D(maxpoolsize)(x)
    n_crop = int(x.shape[1] - timesteps)
    x = Cropping1D(cropping=(0, n_crop))(x)

    decoded = Conv1D(input_dim, kernelsize, activation='linear', padding='same', use_bias=False,
                     input_shape=(timesteps, input_dim), name='autoencoderl')(x)

    autoencoder = Model(inputs, decoded)
    autoencoder.compile(optimizer='Adam', loss='mse')  # mine
    # autoencoder.compile(optimizer='rmsprop', loss='mse')
    autoencoder.summary()
    encoder = Model(inputs, encoded, name='encoded_layer')
    return autoencoder, encoder

def domain_model(encoder):
    flip_layer = GradientReversal(hp_lambda=1)
    dann_in = flip_layer(encoder.output)
    domain_classifier = Flatten(name="do4")(dann_in)
    domain_classifier = BatchNormalization(name="do5")(domain_classifier)
    domain_classifier = Activation("relu", name="do6")(domain_classifier)
    domain_classifier = Dropout(0.5)(domain_classifier)
    domain_classifier = Dense(64, activation='softmax', name="do7")(domain_classifier)
    domain_classifier = Activation("relu", name="do8")(domain_classifier)
    dann_out = Dense(2, activation='softmax', name="domain")(domain_classifier)
    domain_classification_model = Model(inputs=encoder.input, outputs=dann_out)
    return domain_classification_model

@tf.custom_gradient
def reverse_gradient(X, hp_lambda):
    """Flips the sign of the incoming gradient during training."""
    try:
        reverse_gradient.num_calls += 1
    except AttributeError:
        reverse_gradient.num_calls = 1

    grad_name = "GradientReversal%d" % reverse_gradient.num_calls

    @ops.RegisterGradient(grad_name)
    def _flip_gradients(grad):
        return [tf.negative(grad) * hp_lambda]
    #
    # def grad(dy):
    #     return tf.constant(0.0)
    # return tf.negative(X), grad

    # g = K.get_session().graph
    with tf.Graph().as_default() as g:
        with g.gradient_override_map({'Identity': grad_name}):
            y = tf.identity(X)
    # y = tf.identity(X)
    return y


class GradientReversal(Layer):
    """Layer that flips the sign of gradient during training."""

    def __init__(self, hp_lambda, **kwargs):
        super(GradientReversal, self).__init__(**kwargs)
        self.supports_masking = True
        self.hp_lambda = hp_lambda

    # @staticmethod
    def get_output_shape_for(input_shape):
        return input_shape

    def build(self, input_shape):
        # self.trainable_weights = []
        return

    def call(self, x, mask=None):
        return reverse_gradient(x, self.hp_lambda)

    def compute_output_shape(self, input_shape):
        return input_shape

    def get_config(self):
        config = {}
        base_config = super(GradientReversal, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


class ATTMODEL:
    def __init__(self, timesteps, input_dim):
        self.timesteps = timesteps
        self.input_dim = input_dim
        self.autoencoder = self.encoder = self.domain_classification_model = self.comb_model = None


    def initialize(self):
        # first: autoencoder model
        self.autoencoder, self.encoder = autoencoder_model(self.timesteps, self.input_dim)

        # domain adversarial learning: ae+domain
        self.domain_classification_model = domain_model(self.encoder)
        self.domain_classification_model.compile(optimizer="Adam",
                                                 loss=['binary_crossentropy'], metrics=['accuracy'])

        self.autoencoder.compile(optimizer='Adam', loss='mse', metrics=['accuracy'])

        self.comb_model = Model(inputs=self.autoencoder.input,
                                outputs=[self.autoencoder.output, self.domain_classification_model.output])
        self.comb_model.compile(optimizer="Adam",
                                loss=['mse', 'binary_crossentropy'], loss_weights=[1, 200], metrics=['accuracy'], )

        print('Finished initializing model structure......')
        return


def get_filelist(dirname, savebinary=False):
    if savebinary:
        filelist = glob.glob(dirname + '/*.npy')
    else:
        filelist = glob.glob(dirname + '/*.csv')
    filelist.sort(key=cmp_to_key(compare_filename))
    return np.array(filelist)

def filename_from_fullpath(path, without_extension=False):
    filename = os.path.basename(path)
    filename_number = '-1'
    if without_extension:
        filename, ext = os.path.splitext(filename)
        filename_number = re.findall(r"\d+", filename)[0]
    # return filename
    return filename_number

def compare_filename(file1, file2):
    f1 = filename_from_fullpath(file1, True)
    f2 = filename_from_fullpath(file2, True)
    return int(f1) - int(f2)

def cmp_to_key(mycmp):
    'Convert a cmp= function into a key= function'
    class K:
        def __init__(self, obj, *args):
            self.obj = obj
        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0
        def __gt__(self, other):
            return mycmp(self.obj, other.obj) > 0
        def __eq__(self, other):
            return mycmp(self.obj, other.obj) == 0
        def __le__(self, other):
            return mycmp(self.obj, other.obj) <= 0
        def __ge__(self, other):
            return mycmp(self.obj, other.obj) >= 0
        def __ne__(self, other):
            return mycmp(self.obj, other.obj) != 0
    return K

def get_orig_data(dirname, include_time=False):
    filelist = get_filelist(dirname)
    data, filenames= [], []
    for filepath in filelist:
        # tmp = np.genfromtxt(filepath, delimiter=',', skip_header=1) #
        tmp = pd.read_csv(filepath, delimiter=',').values
        acc_data = tmp[:, 1:]
        # filename = filepath.split('\\')[-1][:-4]
        # filenames.append(filename)
        if (not include_time) :
            arr = np.delete(acc_data, 0, axis=0)
            data.append(arr)
        else:
            data.append(acc_data)
    return np.array(data)

def get_max_length(normal_data, mutant_data):
    length = np.array([])
    for data in normal_data:
        length = np.append(length, len(data))
    for data in mutant_data:
        length = np.append(length, len(data))

    return int(np.max(length))

def hotvec(dim, label, num):
    ret = []
    for i in range(num):
        vec = [0] * dim
        vec[label] = 1
        ret.append(vec)
    return np.array(ret)

# load data of two folders respectively
datasetrootdir = r'.\dataset'
normal_dir_name = os.path.join(datasetrootdir, 'normal')
mutant_dir_name = os.path.join(datasetrootdir, 'mutant')
normal_data = get_orig_data(normal_dir_name)
mutant_data = get_orig_data(mutant_dir_name)

maxlen = get_max_length(normal_data, mutant_data)

# transform the list to same sequence length
X_normal_train = sequence.pad_sequences(normal_data, maxlen=maxlen, dtype='float64', padding='post',
                                        truncating='post', value=-1.0)
X_mutant_train = sequence.pad_sequences(mutant_data, maxlen=maxlen, dtype='float64', padding='post',
                                            truncating='post', value=-1.0)
Y_normal = hotvec(2, 0, len(normal_data)).reshape([-1, 2])
Y_mutant = hotvec(2, 1, len(mutant_data)).reshape([-1, 2])

X_train = np.concatenate((X_normal_train, X_mutant_train))
Y_train = np.concatenate((Y_normal, Y_mutant))

timesteps = maxlen
input_dim = np.array(X_train).shape[2]
dtc = ATTMODEL(timesteps=timesteps, input_dim=input_dim)
dtc.initialize()
for epoch in range(300):
    print('run epoch:' + str(epoch))
    stats = dtc.comb_model.train_on_batch(X_train, [X_train, Y_train])