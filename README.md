# Mosaics
A collection of community generated recursive mosaic inscriptions

The first 512 inscriptions that satisfy the following rules will be recognized as valid Mosaics:

- Must be a 100x100 HTML mosaic using inscriptions as tiles (recursive), following the file format generated by the script in this repo. No individual tile can appear more than 10 times in the mosaic.

- Must be inscribed on an uncommon sat (or higher rarity)

- 40% of earnings from initial sale must be pledged to holders of the tile inscriptions in the mosaic, and 10% must be pledged to the Ord core dev fund

## How to generate a mosaic
```
git clone https://github.com/dannydeezy/mosaics
cd mosaics
python3 mosaic.py <YOUR_IMAGE> <LIST_OF_COLLECTION_SLUGS_TO_USE_AS_TILES> "Name of Mosaic"
```

## Examples:
```
python3 mosaic.py ../frogs/coolfrog.webp bitcoin-frogs "We Are All Frogtoshi"
python3 mosaic.py ~/Downloads/MidjourneyArt.jpg  astral-babes,astralchads "Mother Gaia"
```

## Add your collection:
```
python3 download-inscriptions.py <YOUR_COLLECTION_SLUG>
```
example:
```
python3 download-inscriptions.py bitcoin-flowers
```
Then you need to inscribe `ids1.js`, `ids2.js`.. and `colors.js`, and update create a file `info.json` in the `collections/your-slug/` folder (see others)