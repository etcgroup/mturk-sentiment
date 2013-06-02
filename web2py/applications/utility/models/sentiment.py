import simplejson, random

# Values for different ratings
NEGATIVE_RATING = -1
NEUTRAL_RATING = 0
POSITIVE_RATING = 1
SKIP_RATING = 12
TWEET_BATCH_LIMIT = 12

# The maximum number of mistakes on verification tweets before the worker is banned
MAX_STRIKES = 13
# The maximum ratio of strikes to total ratings before the worker is banned
MAX_STRIKE_RATIO = 0.02
# The maximum number of ratings a worker is allowed to provide
MAX_RATINGS = 800

# If the percent of tweets rated positive is over this value, the worker is invalid
TOO_POSITIVE_PERCENT = 0.85
TOO_POSITIVE_RATING_MINIMUM = 300

# WARNING_STRIKES = 10
# WARNING_STRIKE_RATIO = 0.01
WARNING_STRIKES = 10
WARNING_STRIKE_RATIO = 0.01
# how often (in HITs) to include a verification tweet in the rating set
VERIFY_INTERVAL = 2

TWEETS_PER_HIT = 12
DESIRED_RATINGS = 3
SMALL_HIT_PRICE = 0.02
LARGE_HIT_PRICE = 0.03
LARGE_HIT_THRESHOLD = 10

options.sentiment = {
    'price' : [LARGE_HIT_PRICE],
    'mystery_task' : False
    }

db.define_table('tweets',
               db.Field('tweetid', 'bigint'),
               db.Field('name', 'text'),
               db.Field('text', 'text'),
               db.Field('ratings', type='integer', default=0),
               db.Field('skips', type='integer', default=0),
               db.Field('open_hits', type='integer', default=0),
               migrate=migratep, fake_migrate=fake_migratep)

db.define_table('ratings',
               db.Field('study', db.studies),
               db.Field('hitid', 'text'),
               db.Field('workerid', 'text'),
               db.Field('assid', 'text'),
               db.Field('condition', db.conditions),
               db.Field('time', type='datetime', default=now),
               db.Field('worker_rating_count', 'integer'),
               db.Field('duration', 'float'),
               db.Field('ip', 'text'),
               db.Field('tweet', db.tweets),
               db.Field('tweetid', 'bigint'),
               db.Field('rating', 'integer'),
               db.Field('skip', 'boolean', default=False),
               db.Field('isstrike', 'boolean'),
               db.Field('isverify', 'boolean', default=False),
               migrate=migratep, fake_migrate=fake_migratep)


db.define_table('workerstats',
                db.Field('id'),
                db.Field('workerid', 'text'),
                db.Field('ratings', type='integer', default=0),
                db.Field('positives', type='integer', default=0),
                db.Field('neutrals', type='integer', default=0),
                db.Field('negatives', type='integer', default=0),
                db.Field('skips', type='integer', default=0),
                db.Field('strikes', type='integer', default=0),
                db.Field('banned', type='boolean', default=False),
                db.Field('banfinal', type='boolean'),
                migrate=migratep, fake_migrate=fake_migratep)
                
def build_sentiment_indices():
    indices = [
        'CREATE INDEX tweetid ON tweets (tweetid);',
        'CREATE INDEX ratings ON tweets (ratings);',
        'CREATE INDEX open_hits ON tweets (open_hits);',
        'CREATE INDEX hitid ON ratings (hitid);',
        'CREATE INDEX workerid ON ratings (workerid);',
        'CREATE INDEX tweet ON ratings (tweet);',
        'CREATE INDEX rating ON ratings (rating);',
        'CREATE INDEX workerid ON workerstats (workerid);'
    ]
    for create in indices:
        try:
            db.executesql(create)
        except Exception, e:
            print "Failed on %s" %(create)
            print e
        finally:
            db.commit()
    
##
# Get a tweet that the worker rated a while back
##    
def get_verification_tweet(workerid):
    
    # Must have been rated by this worker
    workerCondition = db.ratings.workerid == workerid
    
    # Must be a non-neutral rating
    extremeCondition = (db.ratings.rating == POSITIVE_RATING) | (db.ratings.rating == NEGATIVE_RATING)
    
    # Join tweets against ratings
    joinCondition = db.tweets.id == db.ratings.tweet

    # Group by tweet
    group = db.tweets.id
    
    where = workerCondition & extremeCondition & joinCondition
    
    # Get N tweets
    ordering = '<random>'
    
    query = db(where)
    query = query.select(db.tweets.ALL, db.ratings.worker_rating_count.max(), orderby=ordering, groupby=group)
    
    result = query.first()
    if result is None:
        return None
        
    tweet = result.tweets.as_dict()
    tweet['isverify'] = True
    return tweet

# This is no longer used except in the sandbox
def get_unrated_tweets(workerid, numTweets, desiredRatings):
    print 'resorting to unrated tweets...'
    ordering = db.tweets.ratings
    group = db.tweets.id
    join = db.ratings.on(db.tweets.id == db.ratings.tweet)
    limit = (0,numTweets)
    where = (db.tweets.ratings < desiredRatings)
    having =(db.ratings.id.count() == 0)
    
    query = db(where)
    query = query.select(db.tweets.ALL, orderby=ordering, groupby=group, limitby=limit, left=join, having=having)
    
    return query.as_list()

##
# Get a group of N tweets that the given worker should rate.
##
def get_tweets(workerid, numTweets, desiredRatings):
    tweets = []
    
    hitNumber = hits_done(workerid, request.study)
    if not request.live and ("hits_completed" in request.vars):
        hitNumber = int(request.vars.hits_completed)
    
    # Get the worker info
    workerstats = db(db.workerstats.workerid==workerid).select().first()
    if workerstats == None:
        id = db.workerstats.insert(workerid=workerid)
        db.commit()
        workerstats = db(db.workerstats.id==id).select().first()

    # Check if it is time for a verification tweet
    if hitNumber % VERIFY_INTERVAL == VERIFY_INTERVAL - 1:
        vertweet = get_verification_tweet(workerid)
        if vertweet is not None:
            print 'verifying with',vertweet['id'],vertweet['text']
            tweets.append(vertweet)
        else:
            print "NO VERIFICATION TWEETS FOR WORKER %s ??"%(workerid)
    # Now get the rest of the tweets
    if not request.live and ("tweets" not in request):
        tweets.extend(get_unrated_tweets(workerid, numTweets, desiredRatings))
    else:
        query = db(db.tweets.id.belongs(request.tweets))
        query = query.select(db.tweets.ALL)
        tweets.extend(query.as_list())

    print 'serving up',[t['id'] for t in tweets]
    return tweets

    
def get_worker_level(workerid=None):
    if workerid is None:
        workerid = request.workerid
    
    workerstats = db(db.workerstats.workerid==workerid).select().first()
    if not workerstats:
        return 'good'
    
    if workerstats.ratings > MAX_RATINGS:
        return 'done'
    
    # ban override
    if workerstats.banfinal == False:
        return 'good'
        
    strikeRatio = (workerstats.strikes) / (workerstats.ratings + 1.0)
    
    if (workerstats.strikes >= MAX_STRIKES) and (strikeRatio > MAX_STRIKE_RATIO):
        if not workerstats.banned and not workerstats.banfinal:
            print 'MARKING WORKER %s AS BANNED' %(workerstats.workerid)
            workerstats.update_record(banned=True)
            db.commit()
        print ' == denying worker %s' %(workerid)
        return 'error'
    
    if (workerstats.strikes >= WARNING_STRIKES) and (strikeRatio > WARNING_STRIKE_RATIO):
        print ' == warning worker %s' %(workerid)
        return 'warning'
    
    positivePercent = (workerstats.positives) / (workerstats.ratings + 1)
    if (workerstats.ratings > TOO_POSITIVE_RATING_MINIMUM) and (positivePercent > TOO_POSITIVE_PERCENT):
        if not workerstats.banned and not workerstats.banfinal:
            print 'MARKING WORKER %s AS BANNED (too positive)' %(workerstats.workerid)
            workerstats.update_record(banned=True)
            db.commit()
        print '== denying worker %s' %(workerid)
        return 'error'
        
    if (workerstats.ratings > TOO_POSITIVE_RATING_MINIMUM * 0.8) and (positivePercent > TOO_POSITIVE_PERCENT):
        print ' == warning worker %s (too positive)' %(workerid)
        return 'warning'
    
    return 'good'

def update_worker_stats():
    hasRatings = db.workerstats.ratings > 0
    
    workers = db(hasRatings).select()
    workersChanged = 0
    for workerstats in workers:
        
        ratings = 0
        positives = 0
        neutrals = 0
        negatives = 0
        skips = 0
        strikes = 0
        
        forWorker = db.ratings.workerid == workerstats.workerid
        allratings = db(forWorker).select(orderby=db.ratings.time)
        
        for rating in allratings:
            ratings += 1
            
            if rating.skip:
                skips += 1
                
            if rating.isstrike:
                strikes += 1
                
            if rating.rating == POSITIVE_RATING:
                positives += 1
                
            if rating.rating == NEUTRAL_RATING:
                neutrals += 1
                
            if rating.rating == NEGATIVE_RATING:
                negatives += 1
                
        if workerstats.ratings != ratings \
            or workerstats.skips != skips \
            or workerstats.strikes != strikes \
            or workerstats.positives != positives \
            or workerstats.neutrals != neutrals \
            or workerstats.negatives != negatives:
            
            workerstats.ratings = ratings
            workerstats.skips = skips
            workerstats.strikes = strikes
            workerstats.positives = positives
            workerstats.neutrals = neutrals
            workerstats.negatives = negatives
            workerstats.update_record()
            
            workersChanged += 1
    
    db.commit()
    
    print "Updated %d workers." %(workersChanged)
    
def update_worker_bans():
    hasRatings = db.workerstats.ratings > 0
    
    workers = db(hasRatings).select()
    workersChanged = 0
    for workerstats in workers:
        
        banned = False
        
        strikeRatio = (workerstats.strikes) / (workerstats.ratings + 1.0)
        if (workerstats.strikes >= MAX_STRIKES) and (strikeRatio > MAX_STRIKE_RATIO):
            banned = True
        
        positivePercent = workerstats.positives / (workerstats.ratings + 1.0)
        if (workerstats.ratings > TOO_POSITIVE_RATING_MINIMUM) and (positivePercent > TOO_POSITIVE_PERCENT):
            banned = True
    
        if banned != workerstats.banned:
            if workerstats.banfinal is not None and workerstats.banfinal != banned:
                print 'SKIPPING WORKER %s WITH MANUAL BAN=%s, SUGGEST=%s' %(workerstats.workerid, workerstats.banfinal, banned)
            else:
                print 'MARKING WORKER %s AS BANNED=%s' %(workerstats.workerid, banned)
                workerstats.update_record(banned=banned)
                workersChanged += 1
    
    db.commit()
    
    print 'Changed %s workers' %(workersChanged)
    
# def unban_worker(reason="Reverse inappropriate ban", workerid=None):
    # if workerid is None:
        # workerid = request.workerid
        
    # params = {'WorkerId' : workerid,
              # 'Reason' : reason
              # }
    # turk.ask_turk('UnblockWorker', params)
    
    # workerstats.update_record(banned=False)
        
# def ban_worker(reason="Sentiment ratings were too inconsistent", workerid=None):
    # if workerid is None:
        # workerid = request.workerid
        
    # workerstats = db(db.workerstats.workerid==workerid).select().first()
    
    # turk.block_worker(workerid, reason)
    # print "== BLOCKING WORKER! %s with %s strikes, ratio %s",workerid,workerstats.strikes + strikeIncrease,strikeRatio
    
    # workerstats.update_record(banned=True)
        
def record_tweet_rating(tweetId, rating, isVerify):

    print 'recording',rating,'for',tweetId
    
    study = request.study
    hit = request.hitid
    worker = request.workerid
    ass = request.assid
    ip = request.env.remote_addr
    condition = get_condition(request.condition)
    duration = time.time() - float(request.post_vars.start_time)
    
    
    positiveIncrease = 1 if rating == POSITIVE_RATING else 0
    neutralIncrease = 1 if rating == NEUTRAL_RATING else 0
    negativeIncrease = 1 if rating == NEGATIVE_RATING else 0
    skipIncrease = 1 if rating == SKIP_RATING else 0
    isSkip = False
    if rating == SKIP_RATING:
        isSkip = True
        rating = None
        
    # get the worker and tweet info
    workerstats = db(db.workerstats.workerid==worker).select().first()
    tweet = db(db.tweets.id==tweetId).select().first()
    
    # Check if the tweet was rated before, in which case it is a quality check
    priorRatingsOfTweet = db((db.ratings.tweet==tweetId) & (db.ratings.workerid == worker)).select(db.ratings.rating)
    trueRating = priorRatingsOfTweet.first().rating if len(priorRatingsOfTweet) > 0 else None
    
    # if there is a true rating and it doesn't match, this is a strike
    strikeIncrease = 0
    if (trueRating != None) and (trueRating != rating):
        print '== strike for worker',worker
        strikeIncrease = 1
    
    # add one to the ratings for this tweet
    if isSkip:
        tweet.update_record(skips=db.tweets.skips + 1)
    else:
        tweet.update_record(ratings=db.tweets.ratings + 1)

    
    # insert the rating record
    db.ratings.insert(study=study,
                      hitid=hit,
                      workerid=worker,
                      assid=ass,
                      ip=ip,
                      worker_rating_count=workerstats.ratings + 1,
                      condition=condition,
                      duration=duration,
                      tweet=tweetId,
                      tweetid=tweet.tweetid,
                      rating=rating,
                      skip=isSkip,
                      isstrike=strikeIncrease == 1,
                      isverify=isVerify)
    
    # update the worker
    workerstats.update_record(ratings=db.workerstats.ratings + 1,
                            positives=db.workerstats.positives + positiveIncrease,
                            neutrals=db.workerstats.neutrals + neutralIncrease,
                            negatives=db.workerstats.negatives + negativeIncrease,
                            skips=db.workerstats.skips + skipIncrease,
                            strikes=db.workerstats.strikes + strikeIncrease)

    db.commit()
    
def launch_test_sentiment_study(task='sentiment'):
    study_name = 'teststudy %s 1' % task
    launch_sentiment_study(study_name, " ... test ...", task)

def launch_sentiment_study(name, description, tweet_limit=None, task='sentiment', studySpecific=False):
    hit_params = {
        'assignments': DESIRED_RATINGS,
        'title' : 'Rate Tweet Sentiment (BONUS)',
        'description' : 'Rate the sentiment of tweets. All payments are in bonus. You will be paid within minutes of finishing the HIT.',
        'keywords' : 'tweets, sentiment, bonus',
    }
    
    conditions = options[task]
    study = get_or_make_one(db.studies.name == name,
                            db.studies,
                            {'name' : name,
                             'launch_date' : datetime.now(),
                             'description' : description,
                             'task' : task,
                             'hit_params' : sj.dumps(hit_params, sort_keys=True)})
    study.update_record(conditions = sj.dumps(conditions, sort_keys=True))
    
    # update the count of how many hits each tweet has open
    if studySpecific:
        update_tweet_open_hits(study.id)
    else:
        update_tweet_open_hits()
    
    # get tweets that don't have open hits
    noOpenHitsCondition = db.tweets.open_hits == 0
    
    # get all the tweets that are completely unrated
    # ratingsCondition = db.tweets.ratings + db.tweets.skips == 0
    
    # get at most TWEET_BATCH_LIMIT tweets
    batch_limit = min(tweet_limit, TWEET_BATCH_LIMIT)
    if batch_limit > 0:
        batch_limit = batch_limit - (batch_limit % TWEETS_PER_HIT)
        limit = (0, batch_limit)
    else:
        limit = None
    
    query = db(noOpenHitsCondition)
    query = query.select(db.tweets.id,limitby=limit)
    tweets = query.as_list()
    
    #shuffle the tweets
    random.shuffle(tweets)
    
    # count the total tweets remaining
    query = db(noOpenHitsCondition)
    remaining = query.count(db.tweets.id)
    
    group = []
    hits_scheduled = 0
    for tweet in tweets:
        if len(group) == TWEETS_PER_HIT:
            schedule_hit(datetime.now(), study.id, task, {'tweets': group})
            hits_scheduled += 1
            group = []
            
        group.append(tweet['id'])
    
    if len(group) > 0:
        schedule_hit(datetime.now(), study.id, task, {'tweets': group})
        hits_scheduled += 1
        
    db.commit()
    
    print "Scheduled",hits_scheduled,"hits for",len(tweets),"tweets,",remaining-len(tweets),"remaining."

def get_needed_assignments_by_hit(excludeBanned=False, studyId=None):

    # no skips
    noSkips = (db.ratings.skip != True)

    # no verify tweets
    noVerifies = (db.ratings.isverify != True)

    # join to hits for the hit status
    hitsJoin = (db.ratings.hitid == db.hits.hitid)
    
    # only look at tweets for closed hits
    hitstatusClosed = (db.hits.status.min() == 'closed')
    
    where = noSkips & noVerifies & hitsJoin
    
    # in the proper study
    if studyId is not None:
        where = where & (db.ratings.study == studyId)

    if excludeBanned:
        # no banned users
        notBannedNotOverridden = (db.workerstats.banned == False) & ((db.workerstats.banfinal == False) | (db.workerstats.banfinal == None))
        banOverridden = (db.workerstats.banfinal == False)
        
        where = where & (notBannedNotOverridden | banOverridden)
        
        # join to workers
        where = where & (db.workerstats.workerid == db.ratings.workerid)
    
    count = db.ratings.id.count().with_alias('valid_ratings')
    hitid = db.ratings.hitid.min().with_alias('hitid')
    
    group = db.ratings.tweet
    having = (db.ratings.id.count() < DESIRED_RATINGS) & hitstatusClosed
    
    query = db(where)
    query = query.select(db.ratings.tweet, hitid, count, groupby=group, having=having)
    
    needed = dict()
    total_ratings = 0
    for row in query:
        hitid = row.hitid
        valid_ratings = row.valid_ratings
        
        if hitid not in needed:
            needed[hitid] = 0
        needed[hitid] = max(needed[hitid], DESIRED_RATINGS - valid_ratings)
        total_ratings += DESIRED_RATINGS - valid_ratings
    
    total_assignments = 0
    for hitid, count in needed.iteritems():
        total_assignments += count
    total_cost = (LARGE_HIT_PRICE + 0.005) * total_assignments
        
    print "Need %s assignments to get %s ratings on %s tweets for max cost of $%0.3f" %(
                total_assignments, total_ratings, len(query), total_cost)

    return needed

def add_new_assignments(excludeBanned=False, studyId=None, limit=None):
    neededCounts = get_needed_assignments_by_hit(excludeBanned, studyId)
    
    totalAdded = 0
    totalHits = 0
    for hitid, count in neededCounts.iteritems():
        if limit is not None and totalAdded >= limit:
            print 'Stopping due to limit'
            break
            
        data = turk.ask_turk('ExtendHIT', {
            'HITId' : hitid,
            'MaxAssignmentsIncrement' : count,
            'ExpirationIncrementInSeconds' : 86400 # one day
        })
        
        if turk.get(data, 'IsValid') != 'True':
            print "Unable to increase HITs by %s on %s" %(count, hitid)
        
        db(db.hits.hitid == hitid).update(status='open')
        db.commit()
        
        totalAdded += count
        totalHits += 1
    
    print 'Added %s assignments to %s hits' %(totalAdded, totalHits)

# Remove ratings for the same assignment by the same worker
def clean_duplicate_ratings():
    group = db.ratings.workerid | db.ratings.assid | db.ratings.tweet
    having = db.ratings.id.count() > 1
    duped = db().select(db.ratings.workerid, db.ratings.assid, db.ratings.tweet, groupby=group, having=having)
    
    ratingsRemoved = 0
    tweetAssignmentsAffected = 0
    ratingCount = db(db.ratings.id > 0).count()
    
    for row in duped:
        matchWorker = db.ratings.workerid == row.workerid
        matchAssignment = db.ratings.assid == row.assid
        matchTweet = db.ratings.tweet == row.tweet
        order = db.ratings.time
        ratings = db(matchWorker & matchAssignment & matchTweet).select(orderby=order)
        skippedFirst = False
        for rating in ratings:
            if not skippedFirst:
                skippedFirst = True
                continue
            
            ratingsRemoved += 1
            rating.delete_record()
        
        tweetAssignmentsAffected += 1
    
    db.commit()
    
    print "Removed %s out of all %s ratings, affecting %s worker-assignment-tweets" %(ratingsRemoved, ratingCount, tweetAssignmentsAffected)
    
def force_refresh_hit_status():
    import time
    changed = list()
    all_hits = get_all_hit_objs()
    
    for hit_xml in all_hits:
        status = turk.get(hit_xml, 'HITStatus')
        hitid = turk.get(hit_xml, 'HITId')
            
        hit = db(db.hits.hitid == hitid).select().first()
        if hit is None:
            print 'Lost hit id: %s' %(hitid)
        else:
            newstatus = hit.status
            #log("refreshing %s %s" % (hitid, status))
            if status == u'Assignable':
                newstatus = 'open'
            if status == u'Unassignable':
                newstatus = 'getting done'
            elif status == u'Reviewable' or status == u'Reviewing':
                # Unassignable happens when someone is doing it now
                # The only other option is Assignable
                newstatus = 'closed'
            if newstatus != hit.status:
                changed.append(hitid)
            record_hit_data(hitid=hitid, status=newstatus, xmlcache=hit_xml.toxml())
            
    print 'Changed status of %s hits!' %(len(changed))
    return changed
    
    
def get_tweet_to_open_map(studyId=None):
    
    # un-closed hits
    openCondition = (db.hits.status != 'closed') & (db.hits.status != 'launch canceled')
    
    # study match
    if studyId is not None:
        studyCondition = db.hits.study == studyId
    else:
        studyCondition = db.hits.study == db.hits.study
        
    query = db(openCondition & studyCondition)
    query = query.select(db.hits.othervars)
    hits = query.as_list()

    tweetMap = dict()
    for hit in hits:
        other = simplejson.loads(hit['othervars'])
        tweets = other['tweets']
        
        for tweetId in tweets:
            if tweetId not in tweetMap:
                tweetMap[tweetId] = 0
            tweetMap[tweetId] += 1
    
    return tweetMap

def update_tweet_open_hits(studyId=None):
    
    db(db.tweets).update(open_hits=0)
    
    tweetMap = get_tweet_to_open_map(studyId)
    
    for tweetId, hitCount in tweetMap.iteritems():
        db(db.tweets.id == tweetId).update(open_hits=hitCount)
        
    db.commit()
    
def reset_sentiment_study():
    db.ratings.truncate('RESTART IDENTITY')
    db.workerstats.truncate('RESTART IDENTITY')
    db(db.tweets).update(ratings=0, skips=0)
    
def get_hit_page(operation, page):
    data = turk.ask_turk(operation, {'PageSize' : 100, \
                            'PageNumber' : page,\
                            'SortProperty' : 'Enumeration'})
    print 'Getting page ' + str(page) + ' with '\
          + turk.get(data, 'NumResults') + ' hits of '\
          + turk.get(data,'TotalNumResults')
    return turk.getsx(data,'HIT')
    
def get_all_hit_pages(operation):
    results = []
    i = 1
    while True:
        hits = get_hit_page(operation, i)
        if len(hits) == 0:
            break
        results += hits
        i = i+1
    return results
    
def get_all_hit_objs ():
    return get_all_hit_pages('SearchHITs')
    
def get_lost_hits():
    import time
    lost_hits = list()
    all_hits = get_all_hit_objs()
    
    for hit_xml in all_hits:
        status = turk.get(hit_xml, 'HITStatus')
        
        if status == 'Assignable':
            hitid = turk.get(hit_xml, 'HITId')
            
            hit = db(db.hits.hitid == hitid).select().first()
            if hit is None:
                lost_hits.append(hitid)
        
    return lost_hits
    
def expire_lost_hits():
    lost_hits = get_lost_hits()
    bad_count = 0
    print('Found %s lost hits...' % (len(lost_hits)))
    for hitid in lost_hits:
        try:
            turk.expire_hit(hitid)
        except Exception as e:
            bad_count += 1
            print e
    print('FAILED to expire %d/%d hits!' % (bad_count, len(lost_hits)))

def expire_study_hits(studyId):
    bad_count = 0
    hits = db(db.hits.status.belongs(('open', 'getting done')) & (db.hits.study == studyId)).select()
    for hit in hits:
        try:
            turk.expire_hit(hit.hitid)
        except:
            bad_count += 1
    print('FAILED to expire %d/%d hits!' % (bad_count, len(hits)))

def get_assignment(assid):
    params = {'AssignmentId' : assid}
    return turk.ask_turk('GetAssignment', params)

def my_process_bonus_queue():
    try:
        for row in db().select(db.bonus_queue.ALL):
            #debug_t('Processing bonus queue row %s' % row.id)
            try:
                my_approve_and_bonus_up_to(row.hitid, row.assid, row.worker, float(row.amount), row.reason)
                debug_t('Success!  Deleting row.')
                db(db.bonus_queue.assid == row.assid).delete()
                if False:
                    worker = db(db.workers.workerid == row.worker).select()[0]
                    worker.update_record(bonus_paid=worker.bonus_paid + float(row.amount))
                db.commit()
            except TurkAPIError as e:
                logger_t.error(str(e.value))
    except KeyboardInterrupt:
        debug_t('Quitting.')
        db.rollback()
        raise
    except Exception as e:
        logger_t.error('BAD EXCEPTION!!! How did this happen? letz rollback and die... ' + str(e))
        try:
            db.rollback()
        except Exception as e:
            logger_t.error('Got an exception handling even THAT exception: ' + str(e.value))
        raise
    
def my_approve_and_bonus_up_to(hitid, assid, workerid, bonusamt, reason):
    ass_status = turk.assignment_status(assid, hitid)
    debug_t('Approving $%s ass %s of status %s' %
            (bonusamt, assid, ass_status))

    # if len(turk.get_assignments_for_hit(hitid)) == 0:
        # raise TurkAPIError("...mturk hasn\'t updated their db yet")
        

    # First approve the assignment, but only if it's "submitted"
    if ass_status == u'Submitted':
        turk.approve_assignment(assid)

#     if ass_status == None:
#         log('The XML we are getting for this crapster is %s'
#                       % turk.ask_turk_raw('GetAssignmentsForHIT', {'HITId' : hitid}))

    if turk.assignment_status(assid, hitid) != u'Approved':
        raise TurkAPIError('Trying to bonus a hit that isn\'t ready!  it is %s'
                           % turk.assignment_status(assid, hitid))

    #log('Now it must be approved.  doing bonus of $%s' % bonusamt)

    # Now let's give it a bonus
    if float(bonusamt) == 0.0:
        #log('Oh... nm this is a 0.0 bonus')
        pass
    else:
        turk.give_bonus_up_to(assid, workerid, float(bonusamt), reason)

    # Update the assignment log and verify everything worked
    update_ass_from_mturk(hitid)
    if turk.assignment_status(assid, hitid) != u'Approved' \
            or turk.bonus_total(assid) < float(bonusamt) - .001:
        raise TurkAPIError('Bonus did\'t work! We have %s and %s<%s'
                           % (turk.assignment_status(assid, hitid),
                              turk.bonus_total(assid),
                              float(bonusamt)))