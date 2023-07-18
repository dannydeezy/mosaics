import requests
import sys
import shutil
import os
from PIL import Image, ImageOps, ImageStat
import json
from util import dash_to_camelcase

CONTENT_BASE_URL = "https://ordinals.com/content/"

# If directory images doesn't exist, then create it
IMG_DIR = 'images'
if not os.path.exists(IMG_DIR):
    os.mkdir(IMG_DIR)

def download_inscription_content(id, save_to_folder):
    filename = save_to_folder + '/' + id
    if os.path.exists(filename):
        print('Image already downloaded: ', filename)
        return
    contentUrl = CONTENT_BASE_URL + id
    res = requests.get(contentUrl, stream=True)
    if res.status_code == 200:
        with open(filename,'wb') as f:
            shutil.copyfileobj(res.raw, f)
        print('Image sucessfully Downloaded: ',filename)
    else:
        print('Image Couldn\'t be retrieved')

def fetch_ids_from_ow(slug):
    print("Fetching ids from ordinals wallet for " + slug)
    ordinalsWalletUrl = "https://raw.githubusercontent.com/ordinals-wallet/ordinals-collections/main/collections/" + slug + "/inscriptions.json"
    print(ordinalsWalletUrl)
    # get object response from url
    resp = requests.get(ordinalsWalletUrl)
    # convert json string to json object
    data = json.loads(resp.text)
    return [inscription["id"] for inscription in data]

def fetch_ids_from_deezy(slug):
    print("Fetching ids from deezy for " + slug)
    deezy_slug = slug
    if slug == "bitcoin-frogs":
        deezy_slug = "bitcoin-frogs-v2"
    elif slug == 'astralchads':
        deezy_slug = 'astral-chads'
    deezy_url = "https://raw.githubusercontent.com/dannydeezy/inscription-collection-registry/main/collections/" + deezy_slug + "/ids.csv"
    try:
        resp = requests.get(deezy_url)
        resp.raise_for_status()
    except:
        print("Error fetching ids from deezy for " + slug)
        return []
    return resp.text.split('\n')
def download_inscriptions(slugs):
    for slug in slugs:
        # Sometimes ordinals wallet has incomplete list, so we check from two places.
        print("Downloading inscriptions for " + slug)
        ow_ids = fetch_ids_from_ow(slug)
        print("owIds: " + str(len(ow_ids)))
        deezy_ids = fetch_ids_from_deezy(slug)
        print("deezyIds: " + str(len(deezy_ids)))
        ow_ids_set = set(ow_ids)
        deezy_ids_set = set(deezy_ids)
        missing_ids = deezy_ids_set - ow_ids_set
        ids = ow_ids + list(missing_ids)

        img_folder = IMG_DIR + '/' + slug
        if not os.path.exists(img_folder):
            os.mkdir(img_folder)
        trimmed_ids = [id for id in ids if id != ""]
        for id in trimmed_ids:
            download_inscription_content(id, img_folder)

        trimmed_ids = sorted(trimmed_ids)
        print(slug + ' ' + str(len(trimmed_ids)))
        id_chunks = [trimmed_ids[i:i + 5000] for i in range(0, len(trimmed_ids), 5000)]
        camelcase_slug = dash_to_camelcase(slug)
        if not os.path.exists(f'collections/{slug}'):
            print(f'making dir: collections/{slug}')
            os.mkdir(f'collections/{slug}')
        for i, id_chunk in enumerate(id_chunks):
            ids_file = f'collections/{slug}/ids{i+1}.js'
            with open(ids_file, 'w') as f:
                f.write('const ' + camelcase_slug + f'Ids{i+1}=["' + '","'.join(id_chunk) + '"]')
        colors_list = []
        print("Calculating average colors for " + slug + "...")
        for id in trimmed_ids:
            img = Image.open('images/' + slug + '/' + id)
            average_color_floats = ImageStat.Stat(img).mean
            average_color_ints = list(map(int, average_color_floats))
            if len(average_color_ints) == 1:
                print('Only got one grayscale value for image ' + id + ' in ' + slug + ', will extrapolate to RGB')
                average_color_ints = [average_color_ints[0], average_color_ints[0], average_color_ints[0]]
            colors_list.append([average_color_ints[0], average_color_ints[1], average_color_ints[2]])
        colors_file = f'collections/{slug}/colors.js'
        with open(colors_file, 'w') as f:
            f.write('const ' + camelcase_slug + 'Colors = ' + json.dumps(colors_list, separators=(",", ":")))

if __name__ == '__main__':
    slugs = sys.argv[1].split(',')
    download_inscriptions(slugs)
