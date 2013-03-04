######################

# coding: utf8

#sql to import tweets: COPY tweets (tweetid,name,text) FROM '/home/mjbrooks/sb47-500-tweets.csv' DELIMITERS ',' HEADER CSV;

import random, hashlib, uuid, datetime, time, math
import gluon.contrib.simplejson

if session.flashType:
    response.flashType = session.flashType
    session.flashType = None

response.title = "Tweet Sentiment"

def index():

    error = None
    if request.post_vars.submit:
        error = process_ratings(request.post_vars)
    else:
        response.start_time = time.time()

    # Get some tweets to rate
    tweets = get_tweets(request.workerid, TWEETS_PER_HIT, DESIRED_RATINGS)
    # randomize the tweet order
    random.shuffle(tweets)

    return dict(tweets=tweets, error=error)

    
def process_ratings(post_vars):

    ratings = {}
    for tweetId in request.post_vars.tweet_ids:
        if tweetId not in request.post_vars:
            return "You must rate the sentiment of all of the tweets."
            
        rating = int(request.post_vars[tweetId])
        
        if rating not in [NEGATIVE_RATING, NEUTRAL_RATING, POSITIVE_RATING, SKIP_RATING]:
            return "Invalid rating " + str(rating)
            
        ratings[tweetId] = rating
    
    for id,rating in ratings.iteritems():
        record_tweet_rating(id, rating)
        
    hit_finished()
    