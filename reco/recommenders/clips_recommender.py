"""
Note: Need to have required models in the /recommenders/models/ directory in the codebase
to run.
"""
import os
import time
import pickle
import logging

# Todo: Rename me for better context
G = None

# Scores the clip to clip score relation matrix
ScoreMatrix = None
MixedCategoryClips = {}


def get_clip_max_score(clip_uid):
    return ScoreMatrix[clip_uid]["information"]["Maxscore"]


def get_initial_category_count():
    """
    Return initial count dict for categories for new users clips datasource.
    """
    return {
        "1000": 0, "1001": 0, "1002": 0, "1003": 0, "1004": 0, "1005": 0,
        "1006": 0, "1007": 0, "1008": 0, "1009": 0, "1010": 0, "1011": 0,
        "1012": 0, "1013": 0, "1014": 0, "1015": 0, "1016": 0, "1017": 0,
        "1018": 0, "1019": 0, "1020": 0, "1021": 0, "1022": 0, "1023": 0,
        "1024": 0, "117645": 0, "131470": 0, "13266": 0, "1386": 0, "70323": 0,
        "20097": 0, "264017": 0, "568925": 0, "565773": 0, "571890": 0,
        "25658545-5c1f-4eb3-93a2-5e757ecdfa8c": 0,
        "2f40f294-d92a-4cc8-825c-96c0812e9c8b": 0,
        "52401623-80b5-422f-8738-6b7ea0c80dbb": 0,
        "649e7f05-7f0b-49f2-850b-fb1a224447ad": 0,
        "6773fbe8-18dc-41f3-80b4-256ca7524d0d": 0,
        "9fa8e151-62c0-4bc4-a7f4-c26013253595": 0,
        "f6df003d-584e-4cda-bf6a-d32a8f422d64": 0,
    }


def init_clips_models():
    model_load_start_time = time.time()

    global G
    global ScoreMatrix

    models_dir = os.path.join(os.getcwd(), "recommenders", "models")

    with open(os.path.join(models_dir, "watch_history_graph.sav"), "rb") as f:
        G = pickle.load(f)

    with open(os.path.join(models_dir, "video_score_matrix.sav"), "rb") as f:
        ScoreMatrix = pickle.load(f)

    logging.info(msg={
        "func": "init_clips_models",
        "message": "model_load_time",
        "time_taken_ms": ((time.time() - model_load_start_time) * 1000),
    })


def init_new_users_clips():
    global MixedCategoryClips
    func_start_time = time.time()

    all_clips_id_list = list(ScoreMatrix.keys())
    all_clips_id_list.sort(reverse=True, key=get_clip_max_score)

    # Stores total videos count in each category
    category_to_clips_count_mapping = get_initial_category_count()

    max_clips_from_each_category = 50
    count_of_completed_categories = 0

    # Used to create same output response contract as get_all_recommended_clips
    # function. Return value has to be a dictionary with clip_uid as key and a score
    # as its value. Upstream services uses that to sort response in redis.
    max_score_value = len(
        category_to_clips_count_mapping.keys()
    ) * max_clips_from_each_category

    current_score_value = max_score_value

    for clip_id in list(all_clips_id_list):
        # initialising clip category as None
        category_of_clip = None
        try:
            category_of_clip = ScoreMatrix[clip_id]["information"]["Category"]
            category_to_clips_count_mapping[category_of_clip]
        except Exception as e:
            logging.error(msg={
                "func": "init_new_users_clips",
                "message": "new category found",
                "e": e,
            })
            continue

        # Checking if all categories are completed
        if count_of_completed_categories >= len(category_to_clips_count_mapping.keys()):
            break

        # In case 50 top clips are already served from the category
        # ignore the new ones in favour of clips from other categories.
        if category_to_clips_count_mapping[category_of_clip] >= max_clips_from_each_category:
            continue

        # Increase count of clips served for the category before adding.
        category_to_clips_count_mapping[category_of_clip] += 1

        if category_to_clips_count_mapping[category_of_clip] == max_clips_from_each_category:
            count_of_completed_categories += 1

        # checking if category exists in mixedCategoryClip and adding it if it doesnt exists
        try:
            MixedCategoryClips[category_of_clip]
        except:
            MixedCategoryClips[category_of_clip] = {}

        # Product requirement to priortize freefire clips
        if category_of_clip == "20097" and category_to_clips_count_mapping["20097"] < 10:
            MixedCategoryClips[category_of_clip][clip_id] = max_score_value + 1
            continue

        MixedCategoryClips[category_of_clip][clip_id] = current_score_value

        # reducing the score for next video to be added
        current_score_value -= 1

    logging.info(msg={
        "func": "init_new_users_clips",
        "message": "load_time",
        "time_taken_ms": ((time.time() - func_start_time) * 1000),
    })


def get_global_recommended_clips_based_on_category(category_id):
    """
    Recommends the set of clips for a new user for which model does not have any data
    returns clips mixed from all categories if no specific category is provided
    """
    if category_id == "":
        all_categories = list(MixedCategoryClips.keys())

        allCategoryClips = {}
        for category in all_categories:
            allCategoryClips.update(MixedCategoryClips[category])

        return (dict(allCategoryClips))

    sub_feed_of_specified_category = {}
    try:
        sub_feed_of_specified_category = MixedCategoryClips[category_id]
    except Exception as e:
        logging.error(msg={
            "func": "get_mix_category_recommended_clips",
            "message": "sub feed called for unknown category",
            "e": e,
        })

    return sub_feed_of_specified_category


def blocked_category_in_recommendation(allowed_category_of_clip, category_of_clip):
    """
    blocks all categories except for  allowed category in recommendation
    """
    if allowed_category_of_clip == "" or category_of_clip == allowed_category_of_clip:
        return False

    return True


def get_all_recommended_clips(formatted_user_uid, custom_clips_li, category_id):
    """
    Recommends the full set of clips for a user present at the time
    the model was trained.

    params:
        formatted_user_uid -> Format: "u_{user_id}"
        custom_clips_li -> list of clip uids
    """
    result_clip_to_score_mapping = {}
    watch_history = []

    # If a user hasn't watched any clips,
    # serve her the top clips across all categories
    if not G.has_node(formatted_user_uid):
        if custom_clips_li == None or len(custom_clips_li) == 0:
            return (True, get_global_recommended_clips_based_on_category(category_id))
        else:
            watch_history = custom_clips_li
    else:
        # Already watched videos by the user
        # Embedded in the model while training
        watch_history = list(set(G.neighbors(formatted_user_uid)))
        watch_history.sort(reverse=True, key=get_clip_max_score)

    for source_clip_id in watch_history[:20]:
        # User can send random clip uids in query
        if source_clip_id not in ScoreMatrix:
            continue

        related_score_matrix = ScoreMatrix[source_clip_id]["relation"]
        related_clips_ids = list(related_score_matrix.keys())

        for suggested_clip_id in related_clips_ids:
            category_of_clip = ScoreMatrix[suggested_clip_id]["information"]["Category"]
            if blocked_category_in_recommendation(category_id, category_of_clip):
                continue

            if suggested_clip_id not in result_clip_to_score_mapping:
                result_clip_to_score_mapping[suggested_clip_id] = related_score_matrix[suggested_clip_id]

            result_clip_to_score_mapping[suggested_clip_id] = max(
                result_clip_to_score_mapping[suggested_clip_id], related_score_matrix[suggested_clip_id]
            )

    for watched_clip in watch_history:

        category_of_clip = ScoreMatrix[watched_clip]["information"]["Category"]
        if watched_clip in result_clip_to_score_mapping:
            result_clip_to_score_mapping[watched_clip] = -1

    results = list(result_clip_to_score_mapping.keys())

    def get_result_mapping_scores(clip_uid):
        return result_clip_to_score_mapping[clip_uid]

    results.sort(reverse=True, key=get_result_mapping_scores)
    results = results[:1000]

    final_clips_scores = {}
    for clip_uid in results:
        final_clips_scores[clip_uid] = result_clip_to_score_mapping[clip_uid]

    """
    In case of specific category we might not have any video in relation to prev watched video
    for that category to handle that case we will return default feed for new users
    taking cutoff as 10 as we will need minimum 10 vid in our recommedation to show to user
    This case will arise in case of categories with very less reach.
    """
    if (len(final_clips_scores) < 10):
        # todo: discuss if we have to implement recommendation based on recency for next call
        return (False, get_global_recommended_clips_based_on_category(category_id))

    return (False, final_clips_scores)
