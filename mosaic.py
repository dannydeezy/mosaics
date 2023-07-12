import sys
import os, os.path
import random
import math
import json
from PIL import Image, ImageOps, ImageStat
from multiprocessing import Process, Queue, cpu_count
from util import dash_to_camelcase

# Change these config parameters to suit your needs...
NUM_TILES_PER_ROW = 100
RANDOM_RANGE = 10
REPEAT = 'ALL_INCLUDED' # 'STRICT_NO', 'MINIMIZED', 'ALL_INCLUDED', 'OK',
TILE_SIZE      = 50		# height/width of mosaic tiles in pixels
TILE_MATCH_RES = 8		# tile matching resolution (higher values give better fit but require more processing)
TILE_BLOCK_SIZE = TILE_SIZE / max(min(TILE_MATCH_RES, TILE_SIZE), 1)
DIFF_RANDOM_VAR = 0
MAX_OCCURRENCES_PER_TILE = 10
if REPEAT in ('STRICT_NO', 'ALL_INCLUDED'):
	WORKER_COUNT = 1 # max(cpu_count() - 1, 1)
else:
	WORKER_COUNT =  max(cpu_count() - 1, 1)

OUT_FILE = 'mosaic.jpeg'
HTML_OUT_FILE = 'mosaic.html'
EOQ_VALUE = None
used_tile_data_index_counts = {}
all_have_been_included = False

class TileProcessor:
	def __init__(self, tiles_directory):
		self.tiles_directory = tiles_directory

	def __process_tile(self, tile_path):
		try:
			img = Image.open(tile_path)
			img = ImageOps.exif_transpose(img)
			file_stats = os.stat(tile_path)
			file_bytes = file_stats.st_size
			# tiles must be square, so get the largest square that fits inside the image
			w = img.size[0]
			h = img.size[1]
			min_dimension = min(w, h)
			w_crop = (w - min_dimension) / 2
			h_crop = (h - min_dimension) / 2
			img = img.crop((w_crop, h_crop, w - w_crop, h - h_crop))

			large_tile_img = img.resize((TILE_SIZE, TILE_SIZE), Image.ANTIALIAS)
			small_tile_img = img.resize((int(TILE_SIZE/TILE_BLOCK_SIZE), int(TILE_SIZE/TILE_BLOCK_SIZE)), Image.ANTIALIAS)
			average_color_floats = ImageStat.Stat(img).mean
			average_color = list(map(int, average_color_floats))
			return (large_tile_img.convert('RGB'), small_tile_img.convert('RGB'), file_bytes, average_color)
		except:
			return (None, None)

	def get_tiles(self):
		large_tiles = []
		small_tiles = []
		file_names = []
		file_sizes = []
		average_colors = []

		print('Reading tiles from {}...'.format(self.tiles_directory))

		# step through each ids1.js, ids2.js etc in self.ids_directory
		# search the tiles directory recursively - assumes tiles will be read in alphabetical order
		for root, subFolders, files in os.walk(self.tiles_directory):
			for tile_name in sorted(files):
				print('Reading {:40.40}'.format(tile_name), flush=True, end='\r')
				tile_path = os.path.join(root, tile_name)
				large_tile, small_tile, size_bytes, average_color = self.__process_tile(tile_path)
				if large_tile:
					large_tiles.append(large_tile)
					small_tiles.append(small_tile)
					file_names.append(tile_name)
					file_sizes.append(size_bytes)
					average_colors.append(average_color)

		print('Processed {} tiles.'.format(len(large_tiles)))

		return (large_tiles, small_tiles, file_names, file_sizes, average_colors)

class TargetImage:
	def __init__(self, image_path):
		self.image_path = image_path

	def get_data(self):
		print('Processing main image...')
		img = Image.open(self.image_path)
		# w = img.size[0] * ENLARGEMENT
		# h = img.size[1]	* ENLARGEMENT
		w = NUM_TILES_PER_ROW * TILE_SIZE
		h = w
		large_img = img.resize((w, h), Image.ANTIALIAS)
		w_diff = (w % TILE_SIZE)/2
		h_diff = (h % TILE_SIZE)/2
		
		# if necessary, crop the image slightly so we use a whole number of tiles horizontally and vertically
		if w_diff or h_diff:
			large_img = large_img.crop((w_diff, h_diff, w - w_diff, h - h_diff))

		small_img = large_img.resize((int(w/TILE_BLOCK_SIZE), int(h/TILE_BLOCK_SIZE)), Image.ANTIALIAS)

		image_data = (large_img.convert('RGB'), small_img.convert('RGB'))

		print('Main image processed.')

		return image_data

class TileFitter:
	def __init__(self, tiles_data, file_sizes):
		self.tiles_data = tiles_data
		self.file_sizes = file_sizes

	def __get_tile_diff(self, t1, t2, bail_out_value):
		diff = 0
		# introduce an optional slight random variation that helps prevent repeat image showing up next to each other
		rand_scale = 1 + ((random.random() * DIFF_RANDOM_VAR) - DIFF_RANDOM_VAR / 2)
		for i in range(len(t1)):
			#diff += (abs(t1[i][0] - t2[i][0]) + abs(t1[i][1] - t2[i][1]) + abs(t1[i][2] - t2[i][2]))
			diff += rand_scale * ((t1[i][0] - t2[i][0])**2 + (t1[i][1] - t2[i][1])**2 + (t1[i][2] - t2[i][2])**2)
			if diff > bail_out_value:
				# we know already that this isn't going to be the best fit, so no point continuing with this tile
				return diff
		return diff

	def should_skip(self, tile_index):
		global all_have_been_included
		# If it hasn't been used yet, then we should not skip it
		if tile_index not in used_tile_data_index_counts:
			# print('Tile {} has not been used yet, will not skip'.format(tile_index))
			return False
		# If it has been used, then we might skip it depending on the REPEAT setting. ALL_INCLUDED setting ensures that
		# all tiles have been used before allowing any duplicates...
		if REPEAT in ['STRICT_NO', 'MINIMIZED'] or (REPEAT == 'ALL_INCLUDED' and not all_have_been_included):
			# print('Tile {} has been used before, and not all have been included'.format(tile_index))
			return True
		# If we've exceeded the max occurrences for this tile, then skip it
		if used_tile_data_index_counts[tile_index] >= MAX_OCCURRENCES_PER_TILE:
			# print('Tile {} has been used {} times, which is more than the max allowed'.format(tile_index, used_tile_data_index_counts[tile_index]))
			return True
		return False
	def get_best_fit_tile(self, img_data):
		global all_have_been_included
		best_fit_tile_index = None
		min_diff = sys.maxsize
		tile_index = 0
		if len(used_tile_data_index_counts) == len(self.tiles_data):
			all_have_been_included = True
		# go through each tile in turn looking for the best match for the part of the image represented by 'img_data'
		for i in range(len(self.tiles_data)):
			tile_data = self.tiles_data[i]
			if self.should_skip(tile_index):
				tile_index += 1
				continue
			diff = self.__get_tile_diff(img_data, tile_data, min_diff)
			if diff < min_diff:
				min_diff = diff
				best_fit_tile_index = tile_index
			tile_index += 1

		if best_fit_tile_index not in used_tile_data_index_counts:
			used_tile_data_index_counts[best_fit_tile_index] = 0
		used_tile_data_index_counts[best_fit_tile_index] += 1
		return best_fit_tile_index

def fit_tiles(work_queue, result_queue, tiles_data, file_sizes):
	# this function gets run by the worker processes, one on each CPU core
	tile_fitter = TileFitter(tiles_data, file_sizes)

	while True:
		try:
			img_data, img_coords = work_queue.get(True)
			if img_data == EOQ_VALUE:
				break
			tile_index = tile_fitter.get_best_fit_tile(img_data)
			result_queue.put((img_coords, tile_index))
		except KeyboardInterrupt:
			pass

	# let the result handler know that this worker has finished everything
	result_queue.put((EOQ_VALUE, EOQ_VALUE))

class ProgressCounter:
	def __init__(self, total):
		self.total = total
		self.counter = 0

	def update(self):
		self.counter += 1
		print("Progress: {:04.1f}%".format(100 * self.counter / self.total), flush=True, end='\r')

class MosaicImage:
	def __init__(self, original_img):
		self.image = Image.new(original_img.mode, original_img.size)
		self.x_tile_count = int(original_img.size[0] / TILE_SIZE)
		self.y_tile_count = int(original_img.size[1] / TILE_SIZE)
		self.total_tiles  = self.x_tile_count * self.y_tile_count

	def add_tile(self, tile_data, coords):
		img = Image.new('RGB', (TILE_SIZE, TILE_SIZE))
		img.putdata(tile_data)
		self.image.paste(img, coords)

	def save(self, path):
		self.image.save(path)

def get_scripts_from_slugs(content_base_url, slug_names):
	script_info_str = ""
	id_var_names = []
	color_var_names = []
	for slug in slug_names:
		i = 0
		camelcase_slug = dash_to_camelcase(slug)
		info_file = open('./collections/{}/info.json'.format(slug))
		info = json.load(info_file)
		while True:
			i += 1
			# TODO: replace script_path with the inscription id
			id_file_path = './collections/{}/ids{}.js'.format(slug, i)
			if not os.path.isfile(id_file_path):
				break
			ids_script_src = content_base_url + "/content/" + info["ids" + str(i)]
			script_info_str += '<script src="{}"></script>\n'.format(ids_script_src)
			var_name = camelcase_slug + 'Ids' + str(i)
			id_var_names.append(var_name)
		info_file.close()
		colors_var_name = camelcase_slug + 'Colors'
		colors_script_src = content_base_url + "/content/" + info["colors"]
		script_info_str += '<script src="{}"></script>\n'.format(colors_script_src)
		color_var_names.append(colors_var_name)
	concat_str = 'const inscriptionIds = ' + id_var_names[0]
	color_concat_str = 'const colors = ' + color_var_names[0]
	for var_name in id_var_names[1:]:
		concat_str += '.concat(' + var_name + ')'
	for color_name in color_var_names[1:]:
		color_concat_str += '.concat(' + color_name + ')'
	script_info_str += '<script>\n' + concat_str + ';\n' + color_concat_str + ';\n</script>\n'
	return script_info_str
def generate_html(ordered_id_nums, file_name, content_base_url, image_title, slug_names):
	script_info_str = get_scripts_from_slugs(content_base_url, slug_names)
	img_vw = 100 / NUM_TILES_PER_ROW
	html = """
<!DOCTYPE html>
<html>
<head>
<title>""" + image_title + """</title>
<style>
* {
margin: 0;
padding: 0;
}
body {
background-color:black;
text-align:center;
}
img, .preview {
margin:0;
padding:0;
border:none;
}
.row {
display:flex;
flex-direction:row;
margin:0;
padding:0;
width:100vw;
}
</style>
</head>
<body>""" + script_info_str + """
<script>
const SIZE=""" + str(NUM_TILES_PER_ROW) + """
const orderedIdNums = """ + json.dumps(ordered_id_nums) + '''
const urlParams = new Proxy(new URLSearchParams(window.location.search), {
    get: (searchParams, prop) => searchParams.get(prop),
});
let PREVIEW_WINDOW_WIDTH = 600
if (urlParams.previewWindowWidth) {
    PREVIEW_WINDOW_WIDTH = parseInt(urlParams.previewWindowWidth) || PREVIEW_WINDOW_WIDTH
}
let PREVIEW_FLICKER_LOAD_SECONDS = 5
if (urlParams.flickerLoadSeconds) {
    PREVIEW_FLICKER_LOAD_SECONDS = parseInt(urlParams.flickerLoadSeconds) || PREVIEW_FLICKER_LOAD_SECONDS
}
let SHOW_PREVIEW = window.matchMedia("(max-width: " + PREVIEW_WINDOW_WIDTH + "px)").matches
if (urlParams.download || urlParams.showFull) SHOW_PREVIEW = false
let imageTileSizeStyle = `\nimg, .preview {`
if (urlParams.tileSize) {
    imageTileSizeStyle += `width:${urlParams.tileSize}px; height:${urlParams.tileSize}px;}`
} else {
   imageTileSizeStyle += `width:''' + str(img_vw) +'''vw; height:''' + str(img_vw) +'''vw;}`
}
document.getElementsByTagName("style")[0].innerHTML += imageTileSizeStyle
let currentDiv
let numItemsLoaded = 0
const imgs = []
window.downloadImage = () => {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('2d');
    const imageSize = imgs[0].width
    canvas.width = imageSize * SIZE;
    canvas.height = imageSize * SIZE;
    for (let i = 0; i < imgs.length; i++) {
        const x = Math.floor(i / SIZE)
        const y = i % SIZE
        context.drawImage(imgs[i], y * imageSize, x * imageSize, imageSize, imageSize);
    }
    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = "''' + image_title.replace(' ', '-') + '''.png";
    link.click();
}

const mosaicElement = document.createElement('div')
mosaicElement.id = 'mosaic'
document.body.appendChild(mosaicElement)
for (let i = 0; i < orderedIdNums.length; i++) {
    if (i % SIZE === 0) {
        currentDiv = document.createElement('div')
        currentDiv.className = "row"
    }
    const inscriptionId = inscriptionIds[orderedIdNums[i]]
    const rgbColor = colors[orderedIdNums[i]]
	const url = "''' + content_base_url + '''" + "/content/" + inscriptionId
    const openInscription = () => window.open(url)
    const previewElement = document.createElement('div')
    previewElement.className = 'preview'
    previewElement.style.backgroundColor = 'rgb(' + rgbColor.join(',') + ')'
    const imgElement = document.createElement('img')
    imgElement.onclick = openInscription
    imgElement.onerror = () => {
        imgElement.parentNode && imgElement.parentNode.replaceChild(previewElement,imgElement)
    }
    imgElement.onload = () => {
        numItemsLoaded++
        if (numItemsLoaded === orderedIdNums.length && urlParams.download) {
            window.downloadImage()
        }
    }
    let tileDiv
    if (SHOW_PREVIEW) {
        previewElement.style.visibility = 'hidden'
        previewElement.onclick = () => {
            imgElement.src = url
            previewElement.parentNode && previewElement.parentNode.replaceChild(imgElement, previewElement)
        }
        setTimeout(() => previewElement.style.visibility='visible', Math.random() * PREVIEW_FLICKER_LOAD_SECONDS * 1000)
        tileDiv = previewElement
    } else {
        imgElement.src = url
        tileDiv = imgElement
    }
    imgs.push(imgElement)
    currentDiv.appendChild(tileDiv)
    if (i % SIZE === SIZE - 1) {
        mosaicElement.appendChild(currentDiv)
    }
}
</script>
</body>
</html>

'''
	f = open(file_name, 'w')
	f.write(html)
	print('Wrote output html to', file_name)
def build_mosaic(result_queue, all_tile_data_large, original_img_large, file_names, file_sizes, average_colors, image_title, slug_names):
	mosaic = MosaicImage(original_img_large)
	used_file_names_with_coords_and_sizes = []
	active_workers = WORKER_COUNT
	while True:
		try:
			img_coords, best_fit_tile_index = result_queue.get()

			if img_coords == EOQ_VALUE:
				active_workers -= 1
				if not active_workers:
					break
			else:
				tile_data = all_tile_data_large[best_fit_tile_index]
				mosaic.add_tile(tile_data, img_coords)
				# print(best_fit_tile_index)
				# print(file_names[best_fit_tile_index])
				used_file_names_with_coords_and_sizes.append((file_names[best_fit_tile_index], img_coords, file_sizes[best_fit_tile_index], best_fit_tile_index))

		except KeyboardInterrupt:
			pass

	mosaic.save(OUT_FILE)
	print('\nFinished, wrote output jpeg to', OUT_FILE)
	used_file_names_with_coords_and_sizes.sort(key=lambda a: (a[1][1], a[1][0]))
	ordered_file_names = [x[0] for x in used_file_names_with_coords_and_sizes]
	ordered_file_sizes = [x[2] for x in used_file_names_with_coords_and_sizes]
	ordered_id_nums = [x[3] for x in used_file_names_with_coords_and_sizes]
	position_dict = {}
	total_downloaded_bytes = 0
	for i in range(len(ordered_file_names)):
		file_name = ordered_file_names[i]
		if file_name not in position_dict:
			# position_dict[file_name] = { "p":[], "c": [ordered_colors[i][0], ordered_colors[i][1], ordered_colors[i][2]] }
			position_dict[file_name] = True
			total_downloaded_bytes += ordered_file_sizes[i]
		# position_dict[file_name]["p"].append(i)

	generate_html(ordered_id_nums, "preview-do-not-inscribe.html", "https://ordinals.com", image_title, slug_names)
	generate_html(ordered_id_nums, "mosaic.html", "", image_title, slug_names)
	num_unique_tiles = len(position_dict)
	print('Number of unique tiles:', num_unique_tiles)
	print('Number of download bytes required:', total_downloaded_bytes)

def calculate_distance(point1, point2):
	x1, y1 = point1
	x2, y2 = point2
	x1 += random.randint(0, RANDOM_RANGE)
	y1 += random.randint(0, RANDOM_RANGE)
	x2 += random.randint(0, RANDOM_RANGE)
	y2 += random.randint(0, RANDOM_RANGE)
	return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def sort_queue_items(queue_items, reference_point):
	return sorted(queue_items, key=lambda item: calculate_distance(reference_point, (item[2], item[3])))

def compose(original_img, tiles, image_title, slug_names):
	print('Building mosaic, press Ctrl-C to abort...')
	original_img_large, original_img_small = original_img
	tiles_large, tiles_small, file_names, file_sizes, average_colors = tiles
	# print(file_names[0])
	mosaic = MosaicImage(original_img_large)

	all_tile_data_large = [list(tile.getdata()) for tile in tiles_large]
	all_tile_data_small = [list(tile.getdata()) for tile in tiles_small]

	work_queue   = Queue(WORKER_COUNT)	
	result_queue = Queue()

	try:
		# start the worker processes that will build the mosaic image
		Process(target=build_mosaic, args=(result_queue, all_tile_data_large, original_img_large, file_names, file_sizes, average_colors, image_title, slug_names)).start()

		# start the worker processes that will perform the tile fitting
		for n in range(WORKER_COUNT):
			Process(target=fit_tiles, args=(work_queue, result_queue, all_tile_data_small, file_sizes)).start()

		progress = ProgressCounter(mosaic.x_tile_count * mosaic.y_tile_count)
		queue_items_with_coords = []
		for x in range(mosaic.x_tile_count):
			for y in range(mosaic.y_tile_count):
				large_box = (x * TILE_SIZE, y * TILE_SIZE, (x + 1) * TILE_SIZE, (y + 1) * TILE_SIZE)
				small_box = (x * TILE_SIZE/TILE_BLOCK_SIZE, y * TILE_SIZE/TILE_BLOCK_SIZE, (x + 1) * TILE_SIZE/TILE_BLOCK_SIZE, (y + 1) * TILE_SIZE/TILE_BLOCK_SIZE)
				queue_items_with_coords.append((list(original_img_small.crop(small_box).getdata()), large_box, x, y))
		# shuffle queue_items
		if RANDOM_RANGE > 0:
			queue_items_with_coords = sort_queue_items(queue_items_with_coords, (50, 50))
		else:
			random.shuffle(queue_items_with_coords)
		for item in queue_items_with_coords:
			work_queue.put((item[0], item[1]))
			progress.update()

	except KeyboardInterrupt:
		print('\nHalting, saving partial image please wait...')

	finally:
		# put these special values onto the queue to let the workers know they can terminate
		for n in range(WORKER_COUNT):
			work_queue.put((EOQ_VALUE, EOQ_VALUE))

def show_error(msg):
	print('ERROR: {}'.format(msg))

def mosaic(img_path, tiles_paths, image_title, slug_names):
	image_data = TargetImage(img_path).get_data()
	tiles_data = ([], [], [], [], [])
	for i in range(len(tiles_paths)):
		tp = tiles_paths[i]
		large_tiles, small_tiles, file_names, file_sizes, average_colors = TileProcessor(tp).get_tiles()
		tiles_data[0].extend(large_tiles)
		tiles_data[1].extend(small_tiles)
		tiles_data[2].extend(file_names)
		tiles_data[3].extend(file_sizes)
		tiles_data[4].extend(average_colors)
	if tiles_data[0]:
		print(tiles_data[2][0])
		compose(image_data, tiles_data, image_title, slug_names)
	else:
		show_error("No images found in tiles directory '{}'".format(tiles_paths))

if __name__ == '__main__':
	if len(sys.argv) < 4:
		show_error('Usage: {} <image> <tiles directory>\r'.format(sys.argv[0]))
	else:
		source_image = sys.argv[1]
		slug_names = sys.argv[2].split(',')
		tile_dir_list = ['images/' + slug for slug in slug_names]
		# need to read them in same order that the inscription ids are
		image_title = sys.argv[3]
		if not os.path.isfile(source_image):
			show_error("Unable to find image file '{}'".format(source_image))
		else:
			mosaic(source_image, tile_dir_list, image_title, slug_names)


