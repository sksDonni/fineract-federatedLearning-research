import torch as t
import numpy as np
from sklearn.metrics import accuracy_score
import flwr as fl
from collections import OrderedDict
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

from socket import socket, AF_INET, SOCK_STREAM
import sys
import pickle


def preprocessing(dataset, data, test_size):
    """
    Preprocess dataset

    Parameters
    ----------
    data: DataFrame
        Pandas dataframe containing German dataset.
    """

    global processed_data
    global categorical
    global label_encoders

    # Reset global variables

    processed_data = None
    categorical = None
    label_encoders = {}

    if dataset == "German":
        # Drop savings account and checkings account columns as they contain a lot
        # of NaN values and may not always be available in real life scenarios
        data = data.drop(columns=['Saving accounts', 'Checking account'])

    dat_dict = data.to_dict()
    new_dat_dict = {}

    # rename columns(Make them lowercase and snakecase)
    for key, value in dat_dict.items():
        newKey = key
        if type(key) == str:
            newKey = newKey.lower().replace(' ', '_')
        # if newKey != key:
        new_dat_dict[newKey] = dat_dict[key]
    del dat_dict

    data = pd.DataFrame.from_dict(new_dat_dict)
    del new_dat_dict

    # print(data.describe())
    # print(data.describe(include='O'))

    cols = data.columns
    num_cols = data._get_numeric_data().columns
    categorical = list(set(cols) - set(num_cols))

    # Drop null rows
    data = data.dropna()

    # Encode text columns to number values
    for category in categorical:
        le = LabelEncoder()
        data[category] = le.fit_transform(data[category])
        label_encoders[category] = le

    for col in data.columns:
        if (col not in categorical):
            data[col] = (data[col].astype('float') - np.mean(data[col].astype('float'))) / np.std(
                data[col].astype('float'))

    # print(data.describe())
    # print(data.describe(include='O'))

    processed_data = data

    # Get Training parameters
    if dataset == "German":
        target_col = data.columns[-1]
        x = data.drop(columns=target_col, axis=1)
        y = data[target_col].astype('int')
    elif dataset == "Australian":
        x = data.drop(14, axis=1)
        y = data[14].astype('int')
    elif dataset == "Japanese":
        x = data.drop(15, axis=1)
        y = data[15].astype('int')
    elif dataset == "Taiwan":
        x = data.drop('default_payment_next_month', axis=1)
        y = data['default_payment_next_month'].astype('int')
    elif dataset == "Polish":
        x = data.drop('class', axis=1)
        y = data['class'].astype('int')

    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=test_size)
    x_train = pd.DataFrame(x_train)
    y_train = pd.DataFrame(y_train)
    y_test = pd.DataFrame(y_test)

    sc = StandardScaler()
    x_train = sc.fit_transform(x_train)
    x_test = sc.transform(x_test)

    y_train = y_train[y_train.columns[0]].to_numpy()
    y_test = y_test[y_test.columns[0]].to_numpy()

    return (x_train, x_test, y_train, y_test)


class Net(t.nn.Module):
    def __init__(self, input_channels, output_channels):
        super(Net, self).__init__()
        # Our network:
        # Linear1->relu->Batchnorm->Linear2->relu->Batchnorm->Dropout->Linear3->output
        # Softmax is added in the predict function
        # This applies Linear transformation to input data.
        self.fc1 = t.nn.Linear(input_channels, int(1.5 * input_channels))
        self.fc2 = t.nn.Linear(int(1.5 * input_channels), int(1.5 * input_channels))
        self.fc3 = t.nn.Linear(int(1.5 * input_channels), output_channels)

        self.relu = t.nn.ReLU()
        self.dropout = t.nn.Dropout(p=0.1)
        self.batchnorm1 = t.nn.BatchNorm1d(int(1.5 * input_channels))
        self.batchnorm2 = t.nn.BatchNorm1d(int(1.5 * input_channels))
        self.sigmoid = t.nn.Sigmoid()

    # This must be implemented
    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.batchnorm1(x)
        x = self.relu(self.fc2(x))
        x = self.batchnorm2(x)
        x = self.dropout(x)
        x = self.fc3(x)
        x = self.sigmoid(x)
        return x

    def predict(self, x):
        output = self.forward(x)
        prediction = t.argmax(output, 1)
        return prediction


def classifier_train(epochs, model, optimizer, X, y, criterion):
    losses = []
    #print(X)
    for i in range(epochs):
        # Precit the output for Given input
        y_pred = model.forward(X)
        # Compute Cross entropy loss
        loss = criterion(y_pred, y)
        # Add loss to the list
        losses.append(loss.item())

        # Print loss
        if i % 500 == 0:
            print("Epoch:", i, " Loss:", loss.item())

        # Clear the previous gradients
        optimizer.zero_grad()
        # Compute gradients
        loss.backward()
        # Adjust weights
        optimizer.step()
    return losses


def accuracy(model, X, y):
    output_labels = model.forward(X)
    return criterion(output_labels, y), accuracy_score(model.predict(X), y)


class ClassifierClient(fl.client.NumPyClient):
    def __init__(self,net,X_train_tensor,y_train_tensor,criterion,optimizer,epochs):
        self.net = net
        self.X_train_tensor = X_train_tensor
        self.y_train_tensor = y_train_tensor
        self.criterion = criterion
        self.optimizer = optimizer
        self.epochs = epochs

    def get_parameters(self):
        return [val.cpu().numpy() for _, val in self.net.state_dict().items()]

    def set_parameters(self, parameters):
        params_dict = zip(self.net.state_dict().keys(), parameters)
        state_dict = OrderedDict({k: t.tensor(v) for k, v in params_dict})
        self.net.load_state_dict(state_dict, strict=True)

    def fit(self, parameters, config):
        self.set_parameters(parameters)
        classifier_train(self.epochs, self.net, self.optimizer, self.X_train_tensor, self.y_train_tensor, self.criterion)
        return self.get_parameters(), self.X_train_tensor.shape[0], {}

    def evaluate(self, parameters, config):
        self.set_parameters(parameters)
        loss, acc = accuracy(self.net, self.X_test_tensor, self.y_test_tensor)
        return float(loss), self.X_test_tensor.shape[0], {"accuracy": float(acc)}


if __name__ == '__main__':

    IP = '127.0.0.1'
    SERVER_PORT = 51000
    BUFLEN = 1024

    dataSocket = socket(AF_INET, SOCK_STREAM)
    try:
        dataSocket.connect((IP, SERVER_PORT))
    except:
        print("Unsuccessfully connect to the server, check the address and port")
        sys.exit(1)

    command = input("Train or Predict ?: ")
    dataSocket.send(command.encode())

    # Preparing Data
    german = pd.read_csv("../data/german.csv")
    test_size = 0.20
    processed_data = None
    categorical = None
    label_encoders = {}

    X_train, X_test, y_train, y_test = preprocessing("German", german, test_size)
    X_train_tensor = t.FloatTensor(X_train)
    y_train_tensor = t.tensor(y_train, dtype=t.long)
    X_test_tensor = t.FloatTensor(X_test)
    y_test_tensor = t.tensor(y_test, dtype=t.long)

    # Define the input and output
    input_channels = X_train_tensor.shape[1]
    output_channels = 2

    # Initialize the model
    net = Net(input_channels, output_channels)
    # Define loss criterion
    criterion = t.nn.CrossEntropyLoss()
    # Define the optimizer
    optimizer = t.optim.Adam(net.parameters(), lr=0.001)
    # Number of epochs
    epochs = 5000

    if command == "Train":

        print(">>> Connect Flower server")
        #print(X_train_tensor)
        client = ClassifierClient(net,X_train_tensor,y_train_tensor,criterion,optimizer,epochs)
        fl.client.start_numpy_client("[::]:8085", client=client)

        # for name, param in net.named_parameters():
        #     if param.requires_grad:
        #         print(name, param.data)

        print(">>> Send Model to Server")
        serialized_model = pickle.dumps(net.state_dict())
        dataSocket.send(serialized_model)

        print(">>> Training Finish")


    elif command == "Predict":
        new_model_dict_string = dataSocket.recv(BUFLEN*100)
        new_model_dict = pickle.loads(new_model_dict_string)
        net.load_state_dict(new_model_dict)
        with t.no_grad():
            net.eval()
            y_pred_vector = net(X_test_tensor)
            val_loss = criterion(y_pred_vector, y_test_tensor)
            y_pred = net.predict(X_test_tensor)

            acc = (y_test_tensor == y_pred).sum()/ y_test_tensor.size(0)


        print("Prediction Result:", y_pred)
        print("Score:",val_loss)
        print("Accuracy:", acc)



