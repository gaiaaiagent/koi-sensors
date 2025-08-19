# koi-net-node-template

# Quick Start

## 1. Create Template Repo

Click `Use this template` -> `Create a new repository` and finish the set up process.

## 2. Clone Repo
Clone the resulting repository
```
git clone <your-github-url-here>
```

## 3. Set up Virtual Environment

```
python -m venv
```
For Windows:
```
venv\Scripts\activate
```
For Mac/Linux:
```
source venv\bin\activate
```

## 4. Install dependencies
```
pip install -r requirements.txt
```

## 5. Run node server
```
python -m node
```

# Modifying this Node
Take a look at the [koi-net repo](https://github.com/BlockScience/koi-net) for documentation about the koi-net package and developing nodes. This template provides the basic structure for a full node setup. You'll likely want to start by modifying `config.py` with the RID types your node deals with, and adding some new knowledge handlers in `handlers.py`.