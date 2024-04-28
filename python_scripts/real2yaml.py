import yaml
import cv2
import numpy as np
import os
import pandas as pd
import geopandas as gpd
from osgeo import gdal, osr, ogr
import json
import base64

# Calc ExG Vegetation Index
def calcExG(img):
    # Convert to float
    img = img.astype(np.float32)
    # Calculate ExG
    ExG = 2 * img[:, :, 1] - img[:, :, 0] - img[:, :, 2]
    return ExG

def get_drone_image(dataset, plot_boundary, transform_WGS84_to_UTM,row=None, col=None, plot_id=None):
    # If the plot_id is provided, get the plot boundary
    if plot_id:
        plot_boundary = plot_boundary[plot_boundary['plot'] == plot_id]
    else:
        # TODO: Get the plot boundary baed on row and col
        plot_boundary = plot_boundary[plot_boundary['column'] == col]
        plot_boundary = plot_boundary[plot_boundary['row'] == row]
        pass

    # Get the plot boundary
    plot_boundary_shape = plot_boundary.geometry.values[0]

    # Read the orthomosaic
    src = dataset
    geotransform = src.GetGeoTransform()
    xinit = geotransform[0]
    yinit = geotransform[3]
    xsize = geotransform[1]
    ysize = geotransform[5]
    
    # Crop the geotiff using plot boundary
    # Get the bounding box of the plot boundary
    x_min, y_min, x_max, y_max = plot_boundary_shape.bounds

    # transform the point
    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint(y_max, x_max)
    point.Transform(transform_WGS84_to_UTM)
    x, y = point.GetX(), point.GetY()
    p1 = (x, y)
    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint(y_min, x_min)
    point.Transform(transform_WGS84_to_UTM)
    x, y = point.GetX(), point.GetY()
    p2 = (x, y)


    
    # Get the pixel coordinates
    row1 = int((p1[1] - yinit)/ysize)
    col1 = int((p2[0] - xinit)/xsize)
    row2 = int((p2[1] - yinit)/ysize)
    col2 = int((p1[0] - xinit)/xsize)

    # If the image is one channel
    if src.RasterCount == 1:
        band = src.GetRasterBand(1)
        drone_img = band.ReadAsArray(col1, row1, col2 - col1 + 1, row2 - row1 + 1)
        drone_img = np.ascontiguousarray(drone_img, dtype=np.float32)
        return drone_img, (col1, row1)
    elif src.RasterCount == 3:
        # RGB
        band1 = src.GetRasterBand(1)
        band2 = src.GetRasterBand(2)
        band3 = src.GetRasterBand(3)
        drone_img = np.transpose([band1.ReadAsArray(col1, row1, col2 - col1 + 1, row2 - row1 + 1),
                band2.ReadAsArray(col1, row1, col2 - col1 + 1, row2 - row1 + 1),
                band3.ReadAsArray(col1, row1, col2 - col1 + 1, row2 - row1 + 1)],(1,2,0))
        drone_img = np.ascontiguousarray(drone_img, dtype=np.uint8)

        # RGB 2 BGR
        drone_img = cv2.cvtColor(drone_img, cv2.COLOR_RGB2BGR)

        return drone_img, (col1, row1)
    else:
        return None, None

def calc_crop_traits(dsm, rgb, mask, points, debug=False):
    # Resize dsm to match with the RGB image
    dsm_resized = cv2.resize(dsm, (rgb.shape[1], rgb.shape[0]))
    # Get the height of the crop from the DSM with mask
    # Create a union mask from the points and the mask
    point_mask = np.zeros_like(mask)
    cv2.rectangle(point_mask, (points[0][0], points[0][1]), (points[1][0], points[1][1]), 1, -1)
    crop_mask = cv2.bitwise_and(point_mask, mask)
    # Get the crop height
    crop_height = np.mean(dsm_resized[crop_mask == 1])
    crop_height = float(crop_height)

    # Get Color
    crop_color = np.round(np.mean(rgb[crop_mask == 1], axis=0) / 255, 2)
    # BGR to RGB
    crop_color = crop_color[[2,1,0]]

    if debug:
        # Draw rect on DEM Image
        dsm_resized_disp = cv2.normalize(dsm_resized, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        dsm_resized_disp = cv2.applyColorMap(dsm_resized_disp, cv2.COLORMAP_JET)
        cv2.rectangle(dsm_resized_disp, (points[0][0], points[0][1]), (points[1][0], points[1][1]), (0, 255, 0), 2)
        cv2.imshow('DSM', dsm_resized_disp)
        cv2.imshow('Crop Mask', crop_mask*255)
        cv2.waitKey(0)
    
    return crop_height, crop_color

def json_img_data_to_image(json_data, debug=False):
    # Get the image data
    img_data = json_data['imageData']
    imageHeight = json_data['imageHeight']
    imageWidth = json_data['imageWidth']
    # Decode the base64 string into bytes
    img_data = base64.b64decode(img_data)
    # Convert to numpy array
    img_data = np.frombuffer(img_data, dtype=np.uint8)
    # Decode the image
    img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)

    if debug:
        # Display the image
        cv2.imshow('image', img)
        cv2.waitKey(0)

    return img

def calc_base_height(rgb, dem, debug=False):
    # Resize the DEM to match the RGB image
    dem_resized = cv2.resize(dem, (rgb.shape[1], rgb.shape[0]))
    
    # Calc ExG on the RGB image
    ExG = calcExG(rgb)
    # Normalize image to 0-255
    ExG = cv2.normalize(ExG, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8UC1)

    # Threshold the ExG image
    _, ExG_thresh = cv2.threshold(ExG, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if debug:
        # Display the ExG image
        cv2.imshow('ExG', ExG)
        cv2.imshow('ExG Thresh', ExG_thresh)
        cv2.waitKey(0)

    # Get the base height
    base_height = np.mean(dem_resized[ExG_thresh == 0])
    base_height = float(base_height)
    return base_height
    

if __name__ == '__main__':


    # Debug scale
    debug_scale = 1/4

    # Create a dictionary
    data = {
        'location': 'Davis',
        'year': 2023,
        'crop_types': ['Cowpea', 'Common Beans', 'Sorghum','Weed'],
        'n_beds': 1,
        'n_rows': 1,
    }

    # Read orthophoto
    orthomosaics = ['/data3/Dataset_2023_processing/Davis/2023-06-20/Drone/metashape/2023-06-20-P4-RGB.tif',
                    '/data3/Dataset_2023_processing/Davis/2023-07-18/Drone/metashape/2023-07-18-P4-RGB.tif']
    orthomosaic = orthomosaics[0]
    dataset_rgb = gdal.Open(orthomosaic, gdal.GA_ReadOnly)
    dataset_dem = gdal.Open(orthomosaic.replace('RGB', 'DEM'), gdal.GA_ReadOnly)

    # Read plot boundary json
    plot_boundary = "/home/GEMINI/GEMINI-App-Data/Intermediate/2023/Davis/Davis/Legumes/Plot-Boundary-WGS84.geojson"
    geojson_features = gpd.read_file(plot_boundary)

    # Correctly format the geojson as a FeatureCollection
    geojson = {'type': 'FeatureCollection', 'features': geojson_features}

    # Load the GeoJSON as a GeoDataFrame
    geojson_gdf = gpd.GeoDataFrame.from_features(geojson['features'], crs="EPSG:4326")
    
    # Define the source srs
    source_srs = osr.SpatialReference()
    source_srs.ImportFromEPSG(int(geojson_gdf.crs.to_epsg()))  # WGS84
    target_srs = osr.SpatialReference()
    # print(dataset_rgb.GetProjection())
    target_srs.ImportFromWkt(dataset_rgb.GetProjection())
    # create the coordinate transformation
    transform_WGS84_to_UTM = osr.CoordinateTransformation(source_srs, target_srs)

    # Get the drone image
    cowpea_plots = ["276", "432", "428", "540", "556"]
    plot_id = cowpea_plots[0]
    pixel_values, plot_origin = get_drone_image(dataset_rgb, geojson_gdf, transform_WGS84_to_UTM, plot_id=plot_id)
    pixel_values_dem, _ = get_drone_image(dataset_dem, geojson_gdf, transform_WGS84_to_UTM, plot_id=plot_id)


    # Load image using opencv
    img = pixel_values

    # ExG image
    ExG = calcExG(img)
    # Normalize image to 0-255
    ExG = cv2.normalize(ExG, None, 0, 255, cv2.NORM_MINMAX,dtype=cv2.CV_8UC1)
    # Threshold the ExG image
    _, ExG_mask = cv2.threshold(ExG, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Calculate soil color
    soil_color = np.round(np.mean(img[ExG_mask == 0], axis=0) / 255, 2)
    # BGR to RGB
    soil_color = soil_color[[2,1,0]]
    data['soil_color'] = soil_color.tolist()
    
    # Resize the image
    img_disp = cv2.resize(img, (0, 0), fx=debug_scale, fy=debug_scale)
    
    pixel_values_dem_disp = cv2.normalize(pixel_values_dem, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if 1:
        # Use Colormap
        pixel_values_dem_disp = cv2.applyColorMap(pixel_values_dem_disp, cv2.COLORMAP_JET)    

    dsm_disp = cv2.resize(pixel_values_dem_disp, (img_disp.shape[1], img_disp.shape[0]))
    
    if 0:
        # Concate image
        img_disp = np.concatenate((img_disp, dsm_disp), axis=1)
        # Display the image
        cv2.imshow('RGB / DEM', img_disp)
        cv2.waitKey(0)

    # Create save dir
    save_dir = 'data'
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    # Save the image
    image_name = f"{orthomosaic.split('/')[-1].replace('.tif', '')}_Plot_{plot_id}.png"
    cv2.imwrite(os.path.join(save_dir, image_name), img)

    # Detect plants
    # Just read annotated json for now
    # Load the JSON file
    json_name = image_name.replace('.png', '.json')
    with open(os.path.join('data',json_name)) as f:
        json_data = json.load(f)

    # Convert to DataFrame
    shapes = pd.DataFrame(pd.DataFrame(json_data["shapes"]))
    img = json_img_data_to_image(json_data)

    # Calculate base height
    base_height = calc_base_height(pixel_values, pixel_values_dem, debug=False)


    # Calculate the center of the plot as origin
    geotransform = dataset_rgb.GetGeoTransform()
    xinit = geotransform[0]
    yinit = geotransform[3]
    xsize = geotransform[1]
    ysize = geotransform[5]
    plot_center_x = xinit + (plot_origin[0]+img.shape[1]/2)*xsize
    plot_center_y = yinit + (plot_origin[1]+img.shape[0]/2)*ysize

    data['crops'] = []
    for i in range(len(shapes)):
        points = []
        for j in range(len(shapes['points'][i])):
            x = round(shapes['points'][i][j][0])
            y = round(shapes['points'][i][j][1])
            points.append((x, y))

        plant_center_x = int(sum([x for x, y in points])/len(points))
        plant_center_y = int(sum([y for x, y in points])/len(points))
        plant_width = points[1][0] - points[0][0]
        plant_height = points[1][1] - points[0][1]
        
        # Calculate lat lon fron top_left, width and height from dataset_rgb gdal object
        # Calculate the lat lon

        utm_x = xinit + (plot_origin[0] + plant_center_x)*xsize
        utm_y = yinit + (plot_origin[1] + plant_center_y)*ysize

        # Calculate offset from the center
        plant_loc_x = utm_x - plot_center_x
        plant_loc_y = utm_y - plot_center_y



        # Calc crop height
        crop_height, crop_color = calc_crop_traits(pixel_values_dem, img, ExG_mask, points, debug=False)
        # Subtract base height
        crop_height = round(crop_height - base_height,3)

        # Get crop type
        geojson_gdf_plot = geojson_gdf[geojson_gdf['plot'] == plot_id].copy()
        crop_type = list(geojson_gdf_plot['population'])[0]
        # Make dictionary
        dict = {
                'crop_type': crop_type,
                'bed': int(geojson_gdf_plot.column),
                'row': int(geojson_gdf_plot.row),
                'x': round(plant_loc_x,6),
                'y': round(plant_loc_y,6),
                'plant_color': crop_color.tolist(),
                'plot_center_x': round(plot_center_x, 6),
                'plot_center_y': round(plot_center_y, 6),
                'width': plant_width,
                'height': plant_height,
                'crop_height': crop_height,
        }
        data['crops'].append(dict)
        # print(points)

        
        # Draw debug bounding box on image
        cv2.rectangle(img, (points[0][0], points[0][1]), (points[1][0], points[1][1]), (0, 255, 0), 2)

    if 1:
        cv2.imshow('image', img)
        cv2.waitKey(0)

    # Write the dictionary to a YAML file
    yaml_name = json_name.replace('.json', '.yaml')
    with open(os.path.join('data',yaml_name), 'w') as outfile:
        yaml.dump(data, outfile, default_flow_style=False,sort_keys=False)
    
    