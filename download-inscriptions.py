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

def download_inscriptions(slugs):
    for slug in slugs:
        print("Downloading inscriptions for " + slug)
        url = "https://raw.githubusercontent.com/ordinals-wallet/ordinals-collections/main/collections/" + slug + "/inscriptions.json"
        print(url)
        # get object response from url
        resp = requests.get(url)
        # convert json string to json object
        data = json.loads(resp.text)

        ids = [inscription["id"] for inscription in data]
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
            colors_list.append([average_color_ints[0], average_color_ints[1], average_color_ints[2]])
        colors_file = f'collections/{slug}/colors.js'
        with open(colors_file, 'w') as f:
            f.write('const ' + camelcase_slug + 'Colors = ' + json.dumps(colors_list, separators=(",", ":")))

if __name__ == '__main__':
    slugs = sys.argv[1].split(',')
    download_inscriptions(slugs)
