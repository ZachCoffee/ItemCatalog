from flask import Flask
from flask import render_template, request, redirect, jsonify, url_for, flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Kimono, KimonoItem, User
from flask import session as login_session
from functools import wraps
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Kimono Catalog App"

engine = create_engine('sqlite:///kimonobrands.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template('login.html', STATE=state)

# Connect Google + user to web application
@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps(
            'Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # Get user id from database or add new user
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;'
    '-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output

# User Helper Functions
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


# Disconnect Google + user from web application
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# JSON APIs to view Kimono Information
@app.route('/kimonos/<int:kimono_id>/items/JSON')
def KimonoBrandJSON(kimono_id):
    kimono = session.query(Kimono).filter_by(id=kimono_id).one()
    items = session.query(KimonoItem).filter_by(
        kimono_id=kimono_id).all()
    return jsonify(KimonoItems=[i.serialize for i in items])


@app.route('/kimonos/<int:kimono_id>/items/<int:items_id>/JSON')
def KimonoItemJSON(kimono_id, items_id):
    Kimono_Item = session.query(KimonoItem).filter_by(id=items_id).one()
    return jsonify(Kimono_Item=Kimono_Item.serialize)


@app.route('/kimonos/JSON')
def KimonosJSON():
    kimonos = session.query(Kimono).all()
    return jsonify(kimonos=[r.serialize for r in kimonos])


def login_required(f):
    @wraps(f) # this requires an import
    def wrapper(*args, **kwargs):
        if 'username' not in login_session:
            return redirect('/login')
        return f(*args, **kwargs)
    return wrapper


# Task 1: Show all Kimono Brands
@app.route('/')
@app.route('/kimonos')
def allKimonos():
    kimonos = session.query(Kimono).all()
    return render_template('allKimonos.html', kimonos=kimonos)


# Task 2: Create new Kimono Brand
@app.route('/kimonos/new', methods=['GET', 'POST'])
@login_required
def newKimonoBrand():
    if request.method == 'POST':
        newKimonoBrand = Kimono(name=request.form['name'],
            user_id=login_session['user_id'])
        session.add(newKimonoBrand)
        flash('New Kimono %s Successfully Created' % newKimonoBrand.name)
        session.commit()
        return redirect(url_for('allKimonos'))
    else:
        return render_template('newKimonoBrand.html')


# Task 3: Edit a Kimono Brand
@app.route('/kimonos/<int:kimono_id>/edit', methods=['GET', 'POST'])
@login_required
def editKimonoBrand(kimono_id):
    editedKimonoBrand = session.query(Kimono).filter_by(id=kimono_id).one_or_none()
    creator = getUserInfo(editedKimonoBrand.user_id)
    user = getUserInfo(login_session['user_id'])
    if creator.id != login_session['user_id']:
        flash("You cannot edit this brand because you did not create it!")
        return redirec(url_for('allKimonos'))
    if request.method == 'POST':
        if request.form['name']:
            editedKimonoBrand.name = request.form['name']
            flash('Restaurant Successfully Edited %s' % editedKimonoBrand.name)
            return redirect(url_for('allKimonos'))
    else:
        return render_template(
            'editKimonoBrand.html', kimono=editedKimonoBrand)


# Task 4: Delete a Kimono Brand
@app.route('/kimonos/<int:kimono_id>/delete', methods=['GET', 'POST'])
@login_required
def deleteKimonoBrand(kimono_id):
    brandToDelete = session.query(Kimono).filter_by(id=kimono_id).one_or_none()
    creator = getUserInfo(brandToDelete.user_id)
    user = getUserInfo(login_session['user_id'])
    if creator.id != login_session['user_id']:
        flash("You cannot delete this brand because you did not create it!")
        return redirec(url_for('allKimonos'))
    if request.method == 'POST':
        session.delete(brandToDelete)
        flash('%s Successfully Deleted' % brandToDelete.name)
        session.commit()
        return redirect(url_for('allKimonos', kimono_id=kimono_id))
    else:
        return render_template('deleteKimonoBrand.html', kimono=brandToDelete)


# Task 5: Show Kimono Brand Item
@app.route('/kimonos/<int:kimono_id>/')
@app.route('/kimonos/<int:kimono_id>/items')
def showKimonoItems(kimono_id):
    kimono = session.query(Kimono).filter_by(id=kimono_id).one()
    items = session.query(KimonoItem).filter_by(kimono_id=kimono_id).all()
    return render_template('showKimonoItems.html', items=items, kimono=kimono)


# Task 6: Create New Kimono Item
@app.route('/kimonos/<int:kimono_id>/items/new', methods=['GET', 'POST'])
@login_required
def newKimonoItems(kimono_id):
    kimono = session.query(Kimono).filter_by(id=kimono_id).one_or_none()
    if request.method == 'POST':
        newItem = KimonoItem(name=request.form['name'], price=request.form[
                                'price'], description=request.form[
                                    'description'], kimono_id=kimono_id, user_id=kimono.user_id)
        session.add(newItem)
        session.commit()
        flash('New Menu %s Item Successfully Created' % (newItem.name))
        return redirect(url_for('showKimonoItems', kimono_id=kimono_id))
    else:
        return render_template('newKimonoItems.html', kimono_id=kimono_id)


# Task 7: Edit a Kimono Brand Item
@app.route('/kimonos/<int:kimono_id>/items/<int:items_id>/edit', methods=[
                'GET', 'POST'])
@login_required
def editKimonoItems(kimono_id, items_id):
    editedItem = session.query(KimonoItem).filter_by(id=items_id).one_or_none()
    kimono = session.query(Kimono).filter_by(id=kimono_id).one_or_none()
    creator = getUserInfo(editedItem.user_id)
    user = getUserInfo(login_session['user_id'])
    if creator.id != login_session['user_id']:
        flash("You cannot edit this item because you did not create it!")
        return redirec(url_for('showKimonoItems'))
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['name']
        if request.form['price']:
            editedItem.price = request.form['price']
        session.add(editedItem)
        session.commit()
        flash('Menu Item Successfully Edited')
        return redirect(url_for('showKimonoItems', kimono_id=kimono_id))
    else:
        return render_template(
            'editKimonoItems.html', kimono_id=kimono_id,
            items_id=items_id, item=editedItem)


# Task 8: Delete a Kimono Brand item
@app.route('/kimonos/<int:kimono_id>/items/<int:items_id>/delete', methods=[
            'GET', 'POST'])
@login_required
def deleteKimonoItems(kimono_id, items_id):
    kimono = session.query(Kimono).filter_by(id=kimono_id).one_or_none()
    deleteKimonoItem = session.query(KimonoItem).filter_by(id=items_id).one_or_none()
    creator = getUserInfo(deleteKimonoItem.user_id)
    user = getUserInfo(login_session['user_id'])
    if creator.id != login_session['user_id']:
        flash("You cannot delete this item because you did not create it!")
        return redirec(url_for('showKimonoItems'))
    if request.method == 'POST':
        session.delete(deleteKimonoItem)
        session.commit()
        flash('Menu Item Successfully Deleted')
        return redirect(url_for('showKimonoItems', kimono_id=kimono_id))
    else:
        return render_template(
            'deleteKimonoItems.html', items=deleteKimonoItem)

if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
